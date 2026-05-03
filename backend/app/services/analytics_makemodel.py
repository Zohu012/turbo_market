"""
Dashboard 4 — Make/Model Deep-Dive.

Requires `make` (and usually `model`) in filters. Returns 400 otherwise.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.seller import Seller
from app.models.vehicle import Vehicle
from app.schemas.analytics_filters import AnalyticsFilters
from app.services.analytics_cache import cache_aggregate
from app.services.analytics_filters import apply_filters
from app.services.analytics_helpers import (
    date_trunc, percentile, safe_round, width_bucket,
)


router = APIRouter(prefix="/makemodel", tags=["analytics-makemodel"])


def _require_make(filters: AnalyticsFilters) -> None:
    if not filters.make:
        raise HTTPException(status_code=400, detail="make filter required")


@router.get("/kpis")
async def makemodel_kpis(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    _require_make(filters)

    async def compute():
        # Active aggregates
        active_stmt = apply_filters(
            select(
                func.count().label("active_count"),
                func.avg(Vehicle.price_azn).label("avg_price"),
                func.avg(Vehicle.odometer).label("avg_mileage"),
                percentile(Vehicle.price_azn, 0.5).label("median"),
                percentile(Vehicle.price_azn, 0.10).label("p10"),
                percentile(Vehicle.price_azn, 0.90).label("p90"),
            ),
            filters,
            default_status="active",
        )
        a = (await db.execute(active_stmt)).one()

        # DTS over inactive
        dts_stmt = apply_filters(
            select(
                func.avg(Vehicle.days_to_sell).label("avg_dts"),
                percentile(Vehicle.days_to_sell, 0.5).label("median_dts"),
            ),
            filters.model_copy(update={"status": "inactive"}),
        ).where(Vehicle.days_to_sell.isnot(None))
        d = (await db.execute(dts_stmt)).one()

        # Liquidity = active / deactivated_30d
        since = datetime.now(timezone.utc) - timedelta(days=30)
        deact_count = await db.scalar(
            apply_filters(
                select(func.count(Vehicle.id)),
                filters.model_copy(update={"status": "inactive"}),
            ).where(Vehicle.date_deactivated >= since)
        )
        liquidity = (
            (a.active_count / deact_count) if deact_count else None
        ) if a.active_count is not None else None

        # Dealer/private split
        share_stmt = apply_filters(
            select(
                func.count().filter(Seller.seller_type.in_(("business", "dealer"))).label("dealer"),
                func.count().filter(Seller.seller_type == "private").label("private"),
                func.count().label("total"),
            ),
            filters,
            join_seller=True,
            default_status="active",
        )
        share = (await db.execute(share_stmt)).one()
        total_share = share.total or 0

        # Top cities
        city_stmt = apply_filters(
            select(Vehicle.city.label("city"), func.count().label("count")),
            filters,
            default_status="active",
        ).where(Vehicle.city.isnot(None)).group_by(Vehicle.city).order_by(func.count().desc()).limit(5)
        cities = (await db.execute(city_stmt)).all()

        # Price trend delta (median 30d vs prior 30d)
        async def median_in_window(start: datetime, end: datetime):
            f = filters.model_copy(update={"date_from": start.date(), "date_to": end.date(), "status": None})
            return await db.scalar(
                apply_filters(select(percentile(Vehicle.price_azn, 0.5)), f)
                .where(Vehicle.price_azn.isnot(None))
            )

        now = datetime.now(timezone.utc)
        d30 = now - timedelta(days=30)
        d60 = now - timedelta(days=60)
        try:
            cur = await median_in_window(d30, now)
            prev = await median_in_window(d60, d30)
            trend_pct = ((cur - prev) / prev * 100) if (cur and prev) else None
        except Exception:
            trend_pct = None

        return {
            "active_count": a.active_count or 0,
            "median_price": safe_round(a.median, 0),
            "p10": safe_round(a.p10, 0),
            "p90": safe_round(a.p90, 0),
            "avg_price": safe_round(a.avg_price, 0),
            "avg_mileage": safe_round(a.avg_mileage, 0),
            "avg_dts": safe_round(d.avg_dts, 1),
            "median_dts": safe_round(d.median_dts, 1),
            "dealer_share": round(share.dealer / total_share, 3) if total_share else None,
            "private_share": round(share.private / total_share, 3) if total_share else None,
            "top_cities": [{"city": c.city, "count": c.count} for c in cities],
            "liquidity_score": safe_round(liquidity, 2),
            "deactivated_30d": deact_count or 0,
            "price_trend_30d_pct": safe_round(trend_pct, 1),
        }

    return await cache_aggregate(f"mm/kpis:{filters.cache_key()}", 120, compute)


@router.get("/price-vs-mileage")
async def mm_price_vs_mileage(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    sample: int = Query(default=2000, ge=100, le=5000),
    db: AsyncSession = Depends(get_db),
):
    _require_make(filters)

    async def compute():
        stmt = apply_filters(
            select(
                Vehicle.id, Vehicle.odometer, Vehicle.price_azn, Vehicle.year,
                Vehicle.condition,
            ),
            filters,
            default_status="active",
        ).where(
            Vehicle.odometer.isnot(None),
            Vehicle.price_azn.isnot(None),
            Vehicle.odometer > 0,
        ).order_by(func.random()).limit(sample)
        rows = (await db.execute(stmt)).all()
        return [
            {
                "id": r.id,
                "odometer": r.odometer,
                "price_azn": float(r.price_azn),
                "year": r.year,
                "condition": r.condition,
            }
            for r in rows
        ]

    return await cache_aggregate(f"mm/price-vs-mileage:{sample}:{filters.cache_key()}", 120, compute)


@router.get("/price-by-city")
async def mm_price_by_city(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    _require_make(filters)

    async def compute():
        stmt = apply_filters(
            select(
                Vehicle.city.label("city"),
                func.avg(Vehicle.price_azn).label("avg"),
                percentile(Vehicle.price_azn, 0.5).label("median"),
                func.count().label("count"),
            ),
            filters,
            default_status="active",
        ).where(
            Vehicle.city.isnot(None), Vehicle.price_azn.isnot(None)
        ).group_by(Vehicle.city).order_by(func.count().desc())
        rows = (await db.execute(stmt)).all()
        return [
            {"city": r.city, "avg": safe_round(r.avg, 0), "median": safe_round(r.median, 0), "count": r.count}
            for r in rows
        ]

    return await cache_aggregate(f"mm/price-by-city:{filters.cache_key()}", 120, compute)


@router.get("/price-by-condition")
async def mm_price_by_condition(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    _require_make(filters)

    async def compute():
        stmt = apply_filters(
            select(
                Vehicle.condition.label("condition"),
                func.avg(Vehicle.price_azn).label("avg"),
                percentile(Vehicle.price_azn, 0.5).label("median"),
                func.count().label("count"),
            ),
            filters,
            default_status="active",
        ).where(
            Vehicle.condition.isnot(None), Vehicle.price_azn.isnot(None)
        ).group_by(Vehicle.condition).order_by(func.count().desc())
        rows = (await db.execute(stmt)).all()
        return [
            {"condition": r.condition, "avg": safe_round(r.avg, 0), "median": safe_round(r.median, 0), "count": r.count}
            for r in rows
        ]

    return await cache_aggregate(f"mm/price-by-condition:{filters.cache_key()}", 120, compute)


@router.get("/price-by-transmission")
async def mm_price_by_transmission(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    _require_make(filters)

    async def compute():
        stmt = apply_filters(
            select(
                Vehicle.transmission.label("transmission"),
                func.avg(Vehicle.price_azn).label("avg"),
                percentile(Vehicle.price_azn, 0.5).label("median"),
                func.count().label("count"),
            ),
            filters,
            default_status="active",
        ).where(
            Vehicle.transmission.isnot(None), Vehicle.price_azn.isnot(None)
        ).group_by(Vehicle.transmission).order_by(func.count().desc())
        rows = (await db.execute(stmt)).all()
        return [
            {"transmission": r.transmission, "avg": safe_round(r.avg, 0), "median": safe_round(r.median, 0), "count": r.count}
            for r in rows
        ]

    return await cache_aggregate(f"mm/price-by-transmission:{filters.cache_key()}", 120, compute)


@router.get("/active-vs-deactivated-trend")
async def mm_active_vs_deactivated_trend(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    days: int = Query(default=180, ge=14, le=365),
    interval: str = Query(default="week", pattern="^(day|week|month)$"),
    db: AsyncSession = Depends(get_db),
):
    _require_make(filters)

    async def compute():
        since = datetime.now(timezone.utc) - timedelta(days=days)
        cleared = filters.model_copy(update={"status": None})

        add_b = date_trunc(interval, Vehicle.date_added).label("period")
        add_stmt = apply_filters(
            select(add_b, func.count().label("added")),
            cleared,
        ).where(Vehicle.date_added >= since).group_by(add_b)

        deact_b = date_trunc(interval, Vehicle.date_deactivated).label("period")
        deact_stmt = apply_filters(
            select(deact_b, func.count().label("deactivated")),
            cleared,
        ).where(Vehicle.date_deactivated >= since).group_by(deact_b)

        adds = {r.period.date(): r.added for r in (await db.execute(add_stmt)).all()}
        deacts = {r.period.date(): r.deactivated for r in (await db.execute(deact_stmt)).all()}
        all_dates = sorted(set(adds) | set(deacts))
        return [
            {"period": d.isoformat(), "added": adds.get(d, 0), "deactivated": deacts.get(d, 0)}
            for d in all_dates
        ]

    return await cache_aggregate(
        f"mm/active-vs-deactivated:{days}:{interval}:{filters.cache_key()}", 600, compute
    )


@router.get("/dts-distribution")
async def mm_dts_distribution(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    n_buckets: int = Query(default=20, ge=5, le=60),
    max_days: int = Query(default=365, ge=30, le=1825),
    db: AsyncSession = Depends(get_db),
):
    _require_make(filters)

    async def compute():
        bucket = width_bucket(Vehicle.days_to_sell, 0, max_days, n_buckets).label("bucket")
        stmt = apply_filters(
            select(bucket, func.count().label("count")),
            filters.model_copy(update={"status": "inactive"}),
        ).where(Vehicle.days_to_sell.isnot(None)).group_by(bucket).order_by(bucket)
        rows = (await db.execute(stmt)).all()
        size = max_days / n_buckets
        return [
            {
                "bucket": int(r.bucket),
                "lo": round(max(0, (r.bucket - 1) * size), 1),
                "hi": round(min(max_days, r.bucket * size), 1),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(
        f"mm/dts-dist:{n_buckets}:{max_days}:{filters.cache_key()}", 300, compute
    )


def _vehicle_row(v: Vehicle) -> dict:
    return {
        "id": v.id,
        "turbo_id": v.turbo_id,
        "make": v.make,
        "model": v.model,
        "year": v.year,
        "price_azn": float(v.price_azn) if v.price_azn else None,
        "odometer": v.odometer,
        "city": v.city,
        "condition": v.condition,
        "transmission": v.transmission,
        "url": v.url,
    }


@router.get("/comparables")
async def mm_comparables(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    _require_make(filters)
    base = apply_filters(
        select(Vehicle).order_by(Vehicle.date_added.desc()),
        filters,
        default_status="active",
    )
    total = await db.scalar(
        apply_filters(select(func.count(Vehicle.id)), filters, default_status="active")
    )
    rows = (await db.execute(base.limit(limit).offset(offset))).scalars().all()
    return {"total": total or 0, "items": [_vehicle_row(v) for v in rows]}


@router.get("/recent-deactivated")
async def mm_recent_deactivated(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    days: int = Query(default=30, ge=1, le=180),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    _require_make(filters)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = apply_filters(
        select(Vehicle).order_by(Vehicle.date_deactivated.desc()),
        filters.model_copy(update={"status": "inactive"}),
    ).where(Vehicle.date_deactivated >= since).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {**_vehicle_row(v),
         "date_deactivated": v.date_deactivated.isoformat() if v.date_deactivated else None,
         "days_to_sell": v.days_to_sell}
        for v in rows
    ]


@router.get("/cheapest")
async def mm_cheapest(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    _require_make(filters)
    stmt = apply_filters(
        select(Vehicle).order_by(Vehicle.price_azn.asc()),
        filters, default_status="active",
    ).where(Vehicle.price_azn.isnot(None)).limit(limit)
    return [_vehicle_row(v) for v in (await db.execute(stmt)).scalars().all()]


@router.get("/most-expensive")
async def mm_most_expensive(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    _require_make(filters)
    stmt = apply_filters(
        select(Vehicle).order_by(Vehicle.price_azn.desc()),
        filters, default_status="active",
    ).where(Vehicle.price_azn.isnot(None)).limit(limit)
    return [_vehicle_row(v) for v in (await db.execute(stmt)).scalars().all()]


@router.get("/overpriced")
async def mm_overpriced(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Active rows with price_azn > P75 of the filtered comparable set."""
    _require_make(filters)
    p75 = await db.scalar(
        apply_filters(
            select(percentile(Vehicle.price_azn, 0.75)),
            filters, default_status="active",
        ).where(Vehicle.price_azn.isnot(None))
    )
    if p75 is None:
        return {"items": [], "p75": None}
    stmt = apply_filters(
        select(Vehicle).order_by(Vehicle.price_azn.desc()),
        filters, default_status="active",
    ).where(Vehicle.price_azn > p75).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return {"p75": safe_round(p75, 0), "items": [_vehicle_row(v) for v in rows]}


@router.get("/similar-models")
async def mm_similar_models(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    """Suggest 8 alternative make+model with same body_type, year ±2,
    and price within ±30% of focal median. Excludes the focal pair."""
    _require_make(filters)

    # Focal stats
    focal_stmt = apply_filters(
        select(
            percentile(Vehicle.price_azn, 0.5).label("median"),
            func.avg(Vehicle.year).label("avg_year"),
            func.mode().within_group(Vehicle.body_type).label("body_type"),
        ),
        filters, default_status="active",
    ).where(Vehicle.price_azn.isnot(None))
    focal = (await db.execute(focal_stmt)).one()
    if focal.median is None or focal.body_type is None or focal.avg_year is None:
        return []
    median = float(focal.median)
    yr = int(focal.avg_year)

    # Search query — start from a clean filter so make/model don't restrict
    base = AnalyticsFilters(
        body_type=focal.body_type,
        year_min=yr - 2,
        year_max=yr + 2,
        price_min=median * 0.7,
        price_max=median * 1.3,
        status="active",
    )
    stmt = apply_filters(
        select(
            Vehicle.make.label("make"),
            Vehicle.model.label("model"),
            func.count().label("active_count"),
            percentile(Vehicle.price_azn, 0.5).label("median"),
        ),
        base,
    ).where(
        ~((func.lower(Vehicle.make) == filters.make.lower())
          & (func.lower(Vehicle.model) == (filters.model or "").lower()))
        if filters.model else
        (func.lower(Vehicle.make) != filters.make.lower())
    ).group_by(Vehicle.make, Vehicle.model).order_by(func.count().desc()).limit(8)
    rows = (await db.execute(stmt)).all()
    return [
        {
            "make": r.make,
            "model": r.model,
            "active_count": r.active_count,
            "median_price": safe_round(r.median, 0),
        }
        for r in rows
    ]
