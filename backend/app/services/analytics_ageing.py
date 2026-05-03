"""
Dashboard — Ageing Listings.

Active listings that have been on market beyond threshold days.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.seller import Seller
from app.models.vehicle import Vehicle
from app.schemas.analytics_filters import AnalyticsFilters
from app.services.analytics_cache import cache_aggregate
from app.services.analytics_filters import apply_filters
from app.services.analytics_helpers import percentile, safe_round

router = APIRouter(prefix="/ageing", tags=["analytics-ageing"])


def _age_expr(now: datetime):
    """Days on market: prefer (now - last_activated_at) else (now - date_added)."""
    return func.extract(
        "epoch",
        now - func.coalesce(Vehicle.last_activated_at, Vehicle.date_added),
    ) / 86400


@router.get("/kpis")
async def ageing_kpis(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        now = datetime.now(timezone.utc)
        age = _age_expr(now)

        row = (await db.execute(
            apply_filters(
                select(
                    func.count().filter(age > 30).label("over_30d"),
                    func.count().filter(age > 60).label("over_60d"),
                    func.count().filter(age > 90).label("over_90d"),
                    func.avg(age).filter(age > 30).label("avg_days_over30"),
                    func.sum(Vehicle.price_azn).filter(age > 60).label("value_over60"),
                ),
                filters,
                default_status="active",
            )
        )).one()

        # PERCENTILE_CONT (ordered-set aggregate) does not support FILTER clause in
        # PostgreSQL — compute conditional medians via separate subqueries instead.
        ageing_sq = apply_filters(
            select(Vehicle.price_azn),
            filters,
            default_status="active",
        ).where(_age_expr(now) > 30, Vehicle.price_azn.isnot(None)).subquery()

        fresh_sq = apply_filters(
            select(Vehicle.price_azn),
            filters,
            default_status="active",
        ).where(_age_expr(now) <= 30, Vehicle.price_azn.isnot(None)).subquery()

        median_ageing = await db.scalar(
            select(percentile(ageing_sq.c.price_azn, 0.5)).select_from(ageing_sq)
        )
        median_fresh = await db.scalar(
            select(percentile(fresh_sq.c.price_azn, 0.5)).select_from(fresh_sq)
        )

        return {
            "over_30d": row.over_30d or 0,
            "over_60d": row.over_60d or 0,
            "over_90d": row.over_90d or 0,
            "avg_days_over_30d": safe_round(row.avg_days_over30, 1),
            "value_tied_over_60d_azn": safe_round(row.value_over60, 0),
            "median_price_ageing": safe_round(median_ageing, 0),
            "median_price_fresh": safe_round(median_fresh, 0),
        }

    return await cache_aggregate(f"ageing/kpis:{filters.cache_key()}", 300, compute)


@router.get("/distribution")
async def ageing_distribution(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        now = datetime.now(timezone.utc)
        age = _age_expr(now)

        row = (await db.execute(
            apply_filters(
                select(
                    func.count().filter(age < 30).label("b0_30"),
                    func.count().filter(age >= 30, age < 60).label("b30_60"),
                    func.count().filter(age >= 60, age < 90).label("b60_90"),
                    func.count().filter(age >= 90, age < 120).label("b90_120"),
                    func.count().filter(age >= 120).label("b120_plus"),
                ),
                filters,
                default_status="active",
            )
        )).one()

        return [
            {"range": "0-30", "count": row.b0_30 or 0},
            {"range": "30-60", "count": row.b30_60 or 0},
            {"range": "60-90", "count": row.b60_90 or 0},
            {"range": "90-120", "count": row.b90_120 or 0},
            {"range": "120+", "count": row.b120_plus or 0},
        ]

    return await cache_aggregate(f"ageing/distribution:{filters.cache_key()}", 300, compute)


@router.get("/by-make")
async def ageing_by_make(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        now = datetime.now(timezone.utc)
        age = _age_expr(now)

        rows = (await db.execute(
            apply_filters(
                select(Vehicle.make.label("make"), func.count().label("count")),
                filters,
                default_status="active",
            )
            .where(age > 60)
            .group_by(Vehicle.make)
            .order_by(func.count().desc())
            .limit(limit)
        )).all()

        return [{"make": r.make, "count": r.count} for r in rows]

    return await cache_aggregate(
        f"ageing/by-make:{limit}:{filters.cache_key()}", 300, compute
    )


@router.get("/listings")
async def ageing_listings(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    threshold: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        now = datetime.now(timezone.utc)
        age = _age_expr(now).label("days_on_market")

        base = apply_filters(
            select(Vehicle, age),
            filters,
            join_seller=True,
            default_status="active",
        ).where(age > threshold)

        total = await db.scalar(
            apply_filters(
                select(func.count(Vehicle.id)),
                filters,
                default_status="active",
            ).where(_age_expr(now) > threshold)
        )

        rows = (await db.execute(
            base.order_by(age.desc()).limit(limit).offset(offset)
        )).all()

        items = []
        for row in rows:
            v = row.Vehicle
            items.append({
                "id": v.id,
                "make": v.make,
                "model": v.model,
                "year": v.year,
                "price_azn": float(v.price_azn) if v.price_azn else None,
                "city": v.city,
                "url": v.url,
                "days_on_market": round(float(row.days_on_market), 0) if row.days_on_market is not None else None,
            })
        return {"total": total or 0, "items": items}

    return await cache_aggregate(
        f"ageing/listings:{threshold}:{offset}:{limit}:{filters.cache_key()}", 300, compute
    )
