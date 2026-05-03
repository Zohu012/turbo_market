"""
Dashboard 2 — Market Price.

Tells dealers what cars in a filter set are *actually* selling for.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
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


router = APIRouter(prefix="/price", tags=["analytics-price"])


def _confidence_label(n: int) -> str:
    if n < 10:
        return "low"
    if n < 50:
        return "medium"
    return "high"


@router.get("/kpis")
async def price_kpis(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        stmt = apply_filters(
            select(
                func.avg(Vehicle.price_azn).label("avg"),
                func.min(Vehicle.price_azn).label("min"),
                func.max(Vehicle.price_azn).label("max"),
                func.stddev_samp(Vehicle.price_azn).label("stdev"),
                percentile(Vehicle.price_azn, 0.10).label("p10"),
                percentile(Vehicle.price_azn, 0.25).label("p25"),
                percentile(Vehicle.price_azn, 0.50).label("median"),
                percentile(Vehicle.price_azn, 0.75).label("p75"),
                percentile(Vehicle.price_azn, 0.90).label("p90"),
                func.count().label("count"),
            ),
            filters,
            default_status="active",
        ).where(Vehicle.price_azn.isnot(None))
        row = (await db.execute(stmt)).one()
        return {
            "avg": safe_round(row.avg, 0),
            "min": safe_round(row.min, 0),
            "max": safe_round(row.max, 0),
            "stdev": safe_round(row.stdev, 0),
            "p10": safe_round(row.p10, 0),
            "p25": safe_round(row.p25, 0),
            "median": safe_round(row.median, 0),
            "p75": safe_round(row.p75, 0),
            "p90": safe_round(row.p90, 0),
            "count": row.count or 0,
            "confidence": _confidence_label(row.count or 0),
        }

    return await cache_aggregate(f"price/kpis:{filters.cache_key()}", 300, compute)


@router.get("/distribution")
async def price_distribution(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    n_buckets: int = Query(default=30, ge=5, le=60),
    db: AsyncSession = Depends(get_db),
):
    """30-bucket histogram, bounded at P1/P99 to drop outliers visually."""

    async def compute():
        bounds = await db.execute(
            apply_filters(
                select(
                    percentile(Vehicle.price_azn, 0.01).label("lo"),
                    percentile(Vehicle.price_azn, 0.99).label("hi"),
                ),
                filters,
                default_status="active",
            ).where(Vehicle.price_azn.isnot(None))
        )
        b = bounds.one()
        if b.lo is None or b.hi is None or float(b.hi) <= float(b.lo):
            return {"buckets": [], "lo": None, "hi": None, "n_buckets": n_buckets}
        lo, hi = float(b.lo), float(b.hi)

        bucket = width_bucket(Vehicle.price_azn, lo, hi, n_buckets).label("bucket")
        rows = (await db.execute(
            apply_filters(
                select(bucket, func.count().label("count")),
                filters,
                default_status="active",
            ).where(Vehicle.price_azn.isnot(None)).group_by(bucket).order_by(bucket)
        )).all()
        size = (hi - lo) / n_buckets
        return {
            "lo": round(lo, 0),
            "hi": round(hi, 0),
            "n_buckets": n_buckets,
            "buckets": [
                {
                    "bucket": int(r.bucket),
                    "lo": round(lo + max(0, r.bucket - 1) * size, 0),
                    "hi": round(lo + min(n_buckets, r.bucket) * size, 0),
                    "count": r.count,
                }
                for r in rows
            ],
        }

    return await cache_aggregate(
        f"price/distribution:{n_buckets}:{filters.cache_key()}", 300, compute
    )


@router.get("/by-year")
async def price_by_year(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        stmt = apply_filters(
            select(
                Vehicle.year.label("year"),
                func.avg(Vehicle.price_azn).label("avg"),
                percentile(Vehicle.price_azn, 0.5).label("median"),
                func.count().label("count"),
            ),
            filters,
            default_status="active",
        ).where(
            Vehicle.year.isnot(None), Vehicle.price_azn.isnot(None)
        ).group_by(Vehicle.year).order_by(Vehicle.year)
        rows = (await db.execute(stmt)).all()
        return [
            {
                "year": r.year,
                "avg": safe_round(r.avg, 0),
                "median": safe_round(r.median, 0),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(f"price/by-year:{filters.cache_key()}", 300, compute)


@router.get("/vs-mileage")
async def price_vs_mileage(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    sample: int = Query(default=2000, ge=100, le=5000),
    db: AsyncSession = Depends(get_db),
):
    """Sampled scatter — random LIMIT to keep payload small."""

    async def compute():
        stmt = apply_filters(
            select(
                Vehicle.id, Vehicle.odometer, Vehicle.price_azn, Vehicle.year,
                Vehicle.make, Vehicle.model,
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
                "make": r.make,
                "model": r.model,
            }
            for r in rows
        ]

    return await cache_aggregate(f"price/vs-mileage:{sample}:{filters.cache_key()}", 300, compute)


@router.get("/trend")
async def price_trend_filtered(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    days: int = Query(default=90, ge=7, le=365),
    interval: str = Query(default="week", pattern="^(day|week|month)$"),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        since = datetime.now(timezone.utc) - timedelta(days=days)
        bucket = date_trunc(interval, Vehicle.date_added).label("period")
        stmt = apply_filters(
            select(
                bucket,
                func.avg(Vehicle.price_azn).label("avg"),
                percentile(Vehicle.price_azn, 0.5).label("median"),
                func.count().label("count"),
            ),
            filters,
        ).where(
            Vehicle.date_added >= since, Vehicle.price_azn.isnot(None)
        ).group_by(bucket).order_by(bucket)
        rows = (await db.execute(stmt)).all()
        return [
            {
                "period": r.period.date().isoformat(),
                "avg": safe_round(r.avg, 0),
                "median": safe_round(r.median, 0),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(
        f"price/trend:{days}:{interval}:{filters.cache_key()}", 600, compute
    )


@router.get("/by-city")
async def price_by_city(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=15, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
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
        ).group_by(Vehicle.city).order_by(func.count().desc()).limit(limit)
        rows = (await db.execute(stmt)).all()
        return [
            {
                "city": r.city,
                "avg": safe_round(r.avg, 0),
                "median": safe_round(r.median, 0),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(f"price/by-city:{limit}:{filters.cache_key()}", 300, compute)


@router.get("/by-seller-type")
async def price_by_seller_type(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        stmt = apply_filters(
            select(
                Seller.seller_type.label("seller_type"),
                func.avg(Vehicle.price_azn).label("avg"),
                percentile(Vehicle.price_azn, 0.5).label("median"),
                func.count().label("count"),
            ),
            filters,
            join_seller=True,
            default_status="active",
        ).where(Vehicle.price_azn.isnot(None)).group_by(Seller.seller_type)
        rows = (await db.execute(stmt)).all()
        return [
            {
                "seller_type": r.seller_type or "unknown",
                "avg": safe_round(r.avg, 0),
                "median": safe_round(r.median, 0),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(f"price/by-seller-type:{filters.cache_key()}", 300, compute)


@router.get("/by-condition")
async def price_by_condition(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
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
            {
                "condition": r.condition,
                "avg": safe_round(r.avg, 0),
                "median": safe_round(r.median, 0),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(f"price/by-condition:{filters.cache_key()}", 300, compute)


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
        "date_added": v.date_added.isoformat() if v.date_added else None,
        "url": v.url,
    }


@router.get("/comparables")
async def price_comparables(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="price_asc", pattern="^(price_asc|price_desc|date_desc|odometer_asc)$"),
    db: AsyncSession = Depends(get_db),
):
    sort_map = {
        "price_asc": Vehicle.price_azn.asc(),
        "price_desc": Vehicle.price_azn.desc(),
        "date_desc": Vehicle.date_added.desc(),
        "odometer_asc": Vehicle.odometer.asc(),
    }
    base = apply_filters(
        select(Vehicle),
        filters,
        default_status="active",
    ).where(Vehicle.price_azn.isnot(None))
    total = await db.scalar(
        apply_filters(
            select(func.count(Vehicle.id)), filters, default_status="active"
        ).where(Vehicle.price_azn.isnot(None))
    )
    rows = (await db.execute(base.order_by(sort_map[sort]).limit(limit).offset(offset))).scalars().all()
    return {"total": total or 0, "items": [_vehicle_row(v) for v in rows]}


@router.get("/recent-deactivated")
async def price_recent_deactivated(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    days: int = Query(default=30, ge=1, le=180),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
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
async def price_cheapest(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = apply_filters(
        select(Vehicle).order_by(Vehicle.price_azn.asc()),
        filters,
        default_status="active",
    ).where(Vehicle.price_azn.isnot(None)).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [_vehicle_row(v) for v in rows]


@router.get("/most-expensive")
async def price_most_expensive(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = apply_filters(
        select(Vehicle).order_by(Vehicle.price_azn.desc()),
        filters,
        default_status="active",
    ).where(Vehicle.price_azn.isnot(None)).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [_vehicle_row(v) for v in rows]


@router.get("/outliers")
async def price_outliers(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """IQR-based outliers: rows outside p25−1.5·IQR or p75+1.5·IQR."""
    bounds = await db.execute(
        apply_filters(
            select(
                percentile(Vehicle.price_azn, 0.25).label("p25"),
                percentile(Vehicle.price_azn, 0.75).label("p75"),
            ),
            filters,
            default_status="active",
        ).where(Vehicle.price_azn.isnot(None))
    )
    b = bounds.one()
    if b.p25 is None or b.p75 is None:
        return {"items": [], "lo": None, "hi": None}
    p25, p75 = float(b.p25), float(b.p75)
    iqr = p75 - p25
    lo = p25 - 1.5 * iqr
    hi = p75 + 1.5 * iqr

    stmt = apply_filters(
        select(Vehicle), filters, default_status="active",
    ).where(
        Vehicle.price_azn.isnot(None),
        ((Vehicle.price_azn < lo) | (Vehicle.price_azn > hi)),
    ).order_by(Vehicle.price_azn.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "lo": round(lo, 0),
        "hi": round(hi, 0),
        "items": [_vehicle_row(v) for v in rows],
    }
