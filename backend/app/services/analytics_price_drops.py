"""
Dashboard — Price Drops.

Find vehicles whose price decreased (using price_history table).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.vehicle import PriceHistory, Vehicle
from app.schemas.analytics_filters import AnalyticsFilters
from app.services.analytics_cache import cache_aggregate
from app.services.analytics_filters import apply_filters
from app.services.analytics_helpers import date_trunc, percentile, safe_round

router = APIRouter(prefix="/price-drops", tags=["analytics-price-drops"])


def _vehicle_row(v: Vehicle) -> dict:
    return {
        "id": v.id,
        "turbo_id": v.turbo_id,
        "make": v.make,
        "model": v.model,
        "year": v.year,
        "price_azn": float(v.price_azn) if v.price_azn else None,
        "city": v.city,
        "url": v.url,
        "date_added": v.date_added.isoformat() if v.date_added else None,
    }


@router.get("/kpis")
async def price_drops_kpis(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        now = datetime.now(timezone.utc)
        d7 = now - timedelta(days=7)
        d30 = now - timedelta(days=30)

        # Subquery: vehicle_ids matching filters (active)
        filt_sq = apply_filters(
            select(Vehicle.id), filters, default_status="active"
        ).subquery()

        # For each vehicle in filter, find latest price drop
        # A drop = a history record where price_azn < the previous record's price_azn
        drop_cte = (
            select(
                PriceHistory.vehicle_id,
                func.max(PriceHistory.price_azn).label("old_price"),
                func.min(PriceHistory.price_azn).label("new_price"),
                func.max(PriceHistory.recorded_at).label("last_drop_at"),
            )
            .where(PriceHistory.vehicle_id.in_(select(filt_sq.c.id)))
            .group_by(PriceHistory.vehicle_id)
            .having(func.max(PriceHistory.price_azn) > func.min(PriceHistory.price_azn))
            .cte("drops")
        )

        total_row = (await db.execute(
            select(
                func.count().label("total"),
                func.avg(drop_cte.c.old_price - drop_cte.c.new_price).label("avg_drop_azn"),
                func.avg(
                    (drop_cte.c.old_price - drop_cte.c.new_price) / drop_cte.c.old_price * 100
                ).label("avg_drop_pct"),
                percentile(
                    (drop_cte.c.old_price - drop_cte.c.new_price) / drop_cte.c.old_price * 100,
                    0.5,
                ).label("median_drop_pct"),
                func.count().filter(drop_cte.c.last_drop_at >= d7).label("last_7d"),
                func.count().filter(drop_cte.c.last_drop_at >= d30).label("last_30d"),
            ).select_from(drop_cte)
        )).one()

        return {
            "total_with_drops": total_row.total or 0,
            "avg_drop_azn": safe_round(total_row.avg_drop_azn, 0),
            "avg_drop_pct": safe_round(total_row.avg_drop_pct, 1),
            "median_drop_pct": safe_round(total_row.median_drop_pct, 1),
            "dropped_last_7d": total_row.last_7d or 0,
            "dropped_last_30d": total_row.last_30d or 0,
        }

    return await cache_aggregate(f"price-drops/kpis:{filters.cache_key()}", 300, compute)


@router.get("/recent")
async def price_drops_recent(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        filt_sq = apply_filters(
            select(Vehicle.id), filters, default_status="active"
        ).subquery()

        drop_sq = (
            select(
                PriceHistory.vehicle_id,
                func.max(PriceHistory.price_azn).label("old_price"),
                func.min(PriceHistory.price_azn).label("new_price"),
                func.max(PriceHistory.recorded_at).label("last_drop_at"),
            )
            .where(PriceHistory.vehicle_id.in_(select(filt_sq.c.id)))
            .group_by(PriceHistory.vehicle_id)
            .having(func.max(PriceHistory.price_azn) > func.min(PriceHistory.price_azn))
            .subquery()
        )

        total = await db.scalar(select(func.count()).select_from(drop_sq))

        rows = (await db.execute(
            select(
                Vehicle,
                drop_sq.c.old_price,
                drop_sq.c.new_price,
                drop_sq.c.last_drop_at,
            )
            .join(drop_sq, Vehicle.id == drop_sq.c.vehicle_id)
            .order_by(drop_sq.c.last_drop_at.desc())
            .limit(limit)
            .offset(offset)
        )).all()

        now = datetime.now(timezone.utc)
        items = []
        for row in rows:
            v = row.Vehicle
            old_p = float(row.old_price) if row.old_price else None
            new_p = float(row.new_price) if row.new_price else None
            drop_azn = round(old_p - new_p, 0) if (old_p and new_p) else None
            drop_pct = round((old_p - new_p) / old_p * 100, 1) if (old_p and new_p and old_p > 0) else None
            days_since = (now - row.last_drop_at).days if row.last_drop_at else None
            items.append({
                **_vehicle_row(v),
                "old_price": old_p,
                "new_price": new_p,
                "drop_azn": drop_azn,
                "drop_pct": drop_pct,
                "days_since_drop": days_since,
            })
        return {"total": total or 0, "items": items}

    return await cache_aggregate(
        f"price-drops/recent:{offset}:{limit}:{filters.cache_key()}", 300, compute
    )


@router.get("/by-make")
async def price_drops_by_make(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        filt_sq = apply_filters(
            select(Vehicle.id, Vehicle.make), filters, default_status="active"
        ).subquery()

        drop_sq = (
            select(PriceHistory.vehicle_id)
            .where(PriceHistory.vehicle_id.in_(select(filt_sq.c.id)))
            .group_by(PriceHistory.vehicle_id)
            .having(func.max(PriceHistory.price_azn) > func.min(PriceHistory.price_azn))
            .subquery()
        )

        rows = (await db.execute(
            select(filt_sq.c.make, func.count().label("count"))
            .join(drop_sq, filt_sq.c.id == drop_sq.c.vehicle_id)
            .group_by(filt_sq.c.make)
            .order_by(func.count().desc())
            .limit(limit)
        )).all()

        return [{"make": r.make, "count": r.count} for r in rows]

    return await cache_aggregate(
        f"price-drops/by-make:{limit}:{filters.cache_key()}", 300, compute
    )


@router.get("/trend")
async def price_drops_trend(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        since = datetime.now(timezone.utc) - timedelta(weeks=12)

        filt_sq = apply_filters(
            select(Vehicle.id), filters, default_status="active"
        ).subquery()

        bucket = date_trunc("week", PriceHistory.recorded_at).label("period")
        rows = (await db.execute(
            select(bucket, func.count(func.distinct(PriceHistory.vehicle_id)).label("count"))
            .where(
                PriceHistory.vehicle_id.in_(select(filt_sq.c.id)),
                PriceHistory.recorded_at >= since,
            )
            .group_by(bucket)
            .order_by(bucket)
        )).all()
        return [{"period": r.period.date().isoformat(), "count": r.count} for r in rows]

    return await cache_aggregate(
        f"price-drops/trend:{filters.cache_key()}", 300, compute
    )


@router.get("/distribution")
async def price_drops_distribution(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        filt_sq = apply_filters(
            select(Vehicle.id), filters, default_status="active"
        ).subquery()

        drop_pcts = (
            select(
                PriceHistory.vehicle_id,
                (
                    (func.max(PriceHistory.price_azn) - func.min(PriceHistory.price_azn))
                    / func.max(PriceHistory.price_azn) * 100
                ).label("drop_pct"),
            )
            .where(PriceHistory.vehicle_id.in_(select(filt_sq.c.id)))
            .group_by(PriceHistory.vehicle_id)
            .having(func.max(PriceHistory.price_azn) > func.min(PriceHistory.price_azn))
            .subquery()
        )

        # Bucket into 0-5%, 5-10%, 10-15%, 15-20%, 20-30%, 30%+
        buckets_def = [
            ("0-5%", 0, 5),
            ("5-10%", 5, 10),
            ("10-15%", 10, 15),
            ("15-20%", 15, 20),
            ("20-30%", 20, 30),
            ("30%+", 30, 9999),
        ]
        rows = (await db.execute(select(drop_pcts.c.drop_pct))).scalars().all()
        counts: dict[str, int] = {b[0]: 0 for b in buckets_def}
        for val in rows:
            v = float(val)
            for label, lo, hi in buckets_def:
                if lo <= v < hi:
                    counts[label] += 1
                    break
        return [{"range": k, "count": v} for k, v in counts.items()]

    return await cache_aggregate(
        f"price-drops/distribution:{filters.cache_key()}", 300, compute
    )
