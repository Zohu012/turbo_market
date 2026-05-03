"""
Dashboard 3 — Days-to-Sell.

All endpoints operate on inactive vehicles with `days_to_sell IS NOT NULL`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.seller import Seller
from app.models.vehicle import Vehicle
from app.schemas.analytics_filters import AnalyticsFilters
from app.services.analytics_cache import cache_aggregate
from app.services.analytics_filters import apply_filters
from app.services.analytics_helpers import percentile, safe_round, width_bucket


router = APIRouter(prefix="/dts", tags=["analytics-dts"])


def _dts_filters(filters: AnalyticsFilters) -> AnalyticsFilters:
    """Force status=inactive; the per-row 'days_to_sell IS NOT NULL' guard is
    added directly to each statement below."""
    return filters.model_copy(update={"status": "inactive"})


@router.get("/kpis")
async def dts_kpis(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        f = _dts_filters(filters)

        stmt = apply_filters(
            select(
                func.avg(Vehicle.days_to_sell).label("avg_dts"),
                percentile(Vehicle.days_to_sell, 0.5).label("median_dts"),
                percentile(Vehicle.days_to_sell, 0.25).label("p25"),
                percentile(Vehicle.days_to_sell, 0.75).label("p75"),
                func.count().filter(Vehicle.days_to_sell <= 7).label("under_7d"),
                func.count().filter(Vehicle.days_to_sell <= 30).label("under_30d"),
                func.count().label("total"),
            ),
            f,
        ).where(Vehicle.days_to_sell.isnot(None))
        row = (await db.execute(stmt)).one()
        total = row.total or 0
        p75 = float(row.p75) if row.p75 is not None else None

        ageing_count = None
        if p75 is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(p75))
            ageing_stmt = apply_filters(
                select(func.count(Vehicle.id)),
                filters.model_copy(update={"status": "active"}),
            ).where(Vehicle.date_added < cutoff)
            ageing_count = await db.scalar(ageing_stmt) or 0

        return {
            "avg_dts": safe_round(row.avg_dts, 1),
            "median_dts": safe_round(row.median_dts, 1),
            "fast_threshold_p25": safe_round(row.p25, 1),
            "slow_threshold_p75": safe_round(row.p75, 1),
            "pct_under_7d": round((row.under_7d or 0) / total, 3) if total else None,
            "pct_under_30d": round((row.under_30d or 0) / total, 3) if total else None,
            "total_sold": total,
            "ageing_inventory_count": ageing_count,
        }

    return await cache_aggregate(f"dts/kpis:{filters.cache_key()}", 300, compute)


@router.get("/distribution")
async def dts_distribution(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    n_buckets: int = Query(default=30, ge=5, le=60),
    max_days: int = Query(default=365, ge=30, le=1825),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        bucket = width_bucket(Vehicle.days_to_sell, 0, max_days, n_buckets).label("bucket")
        stmt = apply_filters(
            select(bucket, func.count().label("count")),
            _dts_filters(filters),
        ).where(Vehicle.days_to_sell.isnot(None)).group_by(bucket).order_by(bucket)
        rows = (await db.execute(stmt)).all()
        bucket_size = max_days / n_buckets
        return [
            {
                "bucket": int(r.bucket),
                "lo": round(max(0, (r.bucket - 1) * bucket_size), 1),
                "hi": round(min(max_days, r.bucket * bucket_size), 1),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(
        f"dts/distribution:{n_buckets}:{max_days}:{filters.cache_key()}", 300, compute
    )


@router.get("/by-make-model")
async def dts_by_make_model(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    min_count: int = Query(default=5, ge=1),
    limit: int = Query(default=30, ge=1, le=100),
    order: str = Query(default="fastest", pattern="^(fastest|slowest)$"),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        stmt = apply_filters(
            select(
                Vehicle.make.label("make"),
                Vehicle.model.label("model"),
                func.avg(Vehicle.days_to_sell).label("avg_dts"),
                percentile(Vehicle.days_to_sell, 0.5).label("median_dts"),
                func.count().label("count"),
            ),
            _dts_filters(filters),
        ).where(Vehicle.days_to_sell.isnot(None)).group_by(Vehicle.make, Vehicle.model)
        stmt = stmt.having(func.count() >= min_count)
        order_col = func.avg(Vehicle.days_to_sell).asc() if order == "fastest" else func.avg(Vehicle.days_to_sell).desc()
        stmt = stmt.order_by(order_col).limit(limit)
        rows = (await db.execute(stmt)).all()
        return [
            {
                "make": r.make,
                "model": r.model,
                "avg_dts": safe_round(r.avg_dts, 1),
                "median_dts": safe_round(r.median_dts, 1),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(
        f"dts/by-make-model:{min_count}:{limit}:{order}:{filters.cache_key()}", 300, compute
    )


@router.get("/by-year")
async def dts_by_year(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        stmt = apply_filters(
            select(
                Vehicle.year.label("year"),
                func.avg(Vehicle.days_to_sell).label("avg_dts"),
                percentile(Vehicle.days_to_sell, 0.5).label("median_dts"),
                func.count().label("count"),
            ),
            _dts_filters(filters),
        ).where(Vehicle.year.isnot(None), Vehicle.days_to_sell.isnot(None)).group_by(Vehicle.year).order_by(Vehicle.year)
        rows = (await db.execute(stmt)).all()
        return [
            {
                "year": r.year,
                "avg_dts": safe_round(r.avg_dts, 1),
                "median_dts": safe_round(r.median_dts, 1),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(f"dts/by-year:{filters.cache_key()}", 300, compute)


def _price_band_expr():
    return case(
        (Vehicle.price_azn < 5_000, "<5k"),
        (Vehicle.price_azn < 10_000, "5–10k"),
        (Vehicle.price_azn < 20_000, "10–20k"),
        (Vehicle.price_azn < 35_000, "20–35k"),
        (Vehicle.price_azn < 60_000, "35–60k"),
        (Vehicle.price_azn < 100_000, "60–100k"),
        else_="100k+",
    )


def _mileage_band_expr():
    return case(
        (Vehicle.odometer < 50_000, "<50k"),
        (Vehicle.odometer < 100_000, "50–100k"),
        (Vehicle.odometer < 150_000, "100–150k"),
        (Vehicle.odometer < 200_000, "150–200k"),
        (Vehicle.odometer < 300_000, "200–300k"),
        else_="300k+",
    )


@router.get("/by-price-band")
async def dts_by_price_band(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        band = _price_band_expr().label("band")
        stmt = apply_filters(
            select(
                band,
                func.avg(Vehicle.days_to_sell).label("avg_dts"),
                percentile(Vehicle.days_to_sell, 0.5).label("median_dts"),
                func.count().label("count"),
            ),
            _dts_filters(filters),
        ).where(Vehicle.price_azn.isnot(None), Vehicle.days_to_sell.isnot(None)).group_by(band)
        rows = (await db.execute(stmt)).all()
        order = ["<5k", "5–10k", "10–20k", "20–35k", "35–60k", "60–100k", "100k+"]
        rows_list = sorted(
            [{"band": r.band, "avg_dts": safe_round(r.avg_dts, 1), "median_dts": safe_round(r.median_dts, 1), "count": r.count} for r in rows],
            key=lambda x: order.index(x["band"]) if x["band"] in order else 99,
        )
        return rows_list

    return await cache_aggregate(f"dts/by-price-band:{filters.cache_key()}", 300, compute)


@router.get("/by-city")
async def dts_by_city(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=15, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        stmt = apply_filters(
            select(
                Vehicle.city.label("city"),
                func.avg(Vehicle.days_to_sell).label("avg_dts"),
                percentile(Vehicle.days_to_sell, 0.5).label("median_dts"),
                func.count().label("count"),
            ),
            _dts_filters(filters),
        ).where(Vehicle.city.isnot(None), Vehicle.days_to_sell.isnot(None)).group_by(Vehicle.city).order_by(func.count().desc()).limit(limit)
        rows = (await db.execute(stmt)).all()
        return [
            {"city": r.city, "avg_dts": safe_round(r.avg_dts, 1), "median_dts": safe_round(r.median_dts, 1), "count": r.count}
            for r in rows
        ]

    return await cache_aggregate(f"dts/by-city:{limit}:{filters.cache_key()}", 300, compute)


@router.get("/by-seller-type")
async def dts_by_seller_type(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        stmt = apply_filters(
            select(
                Seller.seller_type.label("seller_type"),
                func.avg(Vehicle.days_to_sell).label("avg_dts"),
                percentile(Vehicle.days_to_sell, 0.5).label("median_dts"),
                func.count().label("count"),
            ),
            _dts_filters(filters),
            join_seller=True,
        ).where(Vehicle.days_to_sell.isnot(None)).group_by(Seller.seller_type)
        rows = (await db.execute(stmt)).all()
        return [
            {
                "seller_type": r.seller_type or "unknown",
                "avg_dts": safe_round(r.avg_dts, 1),
                "median_dts": safe_round(r.median_dts, 1),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(f"dts/by-seller-type:{filters.cache_key()}", 300, compute)


@router.get("/by-mileage-band")
async def dts_by_mileage_band(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        band = _mileage_band_expr().label("band")
        stmt = apply_filters(
            select(
                band,
                func.avg(Vehicle.days_to_sell).label("avg_dts"),
                percentile(Vehicle.days_to_sell, 0.5).label("median_dts"),
                func.count().label("count"),
            ),
            _dts_filters(filters),
        ).where(Vehicle.odometer.isnot(None), Vehicle.days_to_sell.isnot(None)).group_by(band)
        rows = (await db.execute(stmt)).all()
        order = ["<50k", "50–100k", "100–150k", "150–200k", "200–300k", "300k+"]
        return sorted(
            [{"band": r.band, "avg_dts": safe_round(r.avg_dts, 1), "median_dts": safe_round(r.median_dts, 1), "count": r.count} for r in rows],
            key=lambda x: order.index(x["band"]) if x["band"] in order else 99,
        )

    return await cache_aggregate(f"dts/by-mileage-band:{filters.cache_key()}", 300, compute)


@router.get("/by-body-type")
async def dts_by_body_type(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        stmt = apply_filters(
            select(
                Vehicle.body_type.label("body_type"),
                func.avg(Vehicle.days_to_sell).label("avg_dts"),
                percentile(Vehicle.days_to_sell, 0.5).label("median_dts"),
                func.count().label("count"),
            ),
            _dts_filters(filters),
        ).where(Vehicle.body_type.isnot(None), Vehicle.days_to_sell.isnot(None)).group_by(Vehicle.body_type).order_by(func.count().desc())
        rows = (await db.execute(stmt)).all()
        return [
            {
                "body_type": r.body_type,
                "avg_dts": safe_round(r.avg_dts, 1),
                "median_dts": safe_round(r.median_dts, 1),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(f"dts/by-body-type:{filters.cache_key()}", 300, compute)


@router.get("/active-too-long")
async def active_too_long(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Active rows whose age exceeds the P75 days-to-sell of the same filter set."""

    p75 = await db.scalar(
        apply_filters(
            select(percentile(Vehicle.days_to_sell, 0.75)),
            _dts_filters(filters),
        ).where(Vehicle.days_to_sell.isnot(None))
    )
    if p75 is None:
        return {"items": [], "total": 0, "p75_days": None}
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(p75))

    base = apply_filters(
        select(Vehicle).order_by(Vehicle.date_added.asc()),
        filters.model_copy(update={"status": "active"}),
    ).where(Vehicle.date_added < cutoff)

    total = await db.scalar(
        apply_filters(
            select(func.count(Vehicle.id)),
            filters.model_copy(update={"status": "active"}),
        ).where(Vehicle.date_added < cutoff)
    )

    rows = (await db.execute(base.limit(limit).offset(offset))).scalars().all()
    return {
        "p75_days": safe_round(p75, 1),
        "total": total or 0,
        "items": [
            {
                "id": v.id,
                "turbo_id": v.turbo_id,
                "make": v.make,
                "model": v.model,
                "year": v.year,
                "price_azn": float(v.price_azn) if v.price_azn else None,
                "odometer": v.odometer,
                "city": v.city,
                "date_added": v.date_added.isoformat(),
                "age_days": (datetime.now(timezone.utc) - v.date_added).days,
                "url": v.url,
            }
            for v in rows
        ],
    }


@router.get("/recent-fast-sales")
async def recent_fast_sales(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    days: int = Query(default=14, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Inactive rows deactivated in the last `days` whose DTS is ≤ P25."""
    p25 = await db.scalar(
        apply_filters(
            select(percentile(Vehicle.days_to_sell, 0.25)),
            _dts_filters(filters),
        ).where(Vehicle.days_to_sell.isnot(None))
    )
    if p25 is None:
        return {"items": [], "p25_days": None}

    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = apply_filters(
        select(Vehicle).order_by(Vehicle.date_deactivated.desc()),
        _dts_filters(filters),
    ).where(
        Vehicle.date_deactivated >= since,
        Vehicle.days_to_sell.isnot(None),
        Vehicle.days_to_sell <= p25,
    ).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "p25_days": safe_round(p25, 1),
        "items": [
            {
                "id": v.id,
                "turbo_id": v.turbo_id,
                "make": v.make,
                "model": v.model,
                "year": v.year,
                "price_azn": float(v.price_azn) if v.price_azn else None,
                "odometer": v.odometer,
                "city": v.city,
                "days_to_sell": v.days_to_sell,
                "date_deactivated": v.date_deactivated.isoformat() if v.date_deactivated else None,
                "url": v.url,
            }
            for v in rows
        ],
    }
