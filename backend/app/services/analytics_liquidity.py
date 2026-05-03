"""
Dashboard — Liquidity.

Turnover = deactivated_30d / avg_active. Days of supply = 30 / turnover_rate.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.vehicle import Vehicle
from app.schemas.analytics_filters import AnalyticsFilters
from app.services.analytics_cache import cache_aggregate
from app.services.analytics_filters import apply_filters
from app.services.analytics_helpers import date_trunc, safe_round

router = APIRouter(prefix="/liquidity", tags=["analytics-liquidity"])


@router.get("/kpis")
async def liquidity_kpis(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        now = datetime.now(timezone.utc)
        d30 = now - timedelta(days=30)

        active_count = await db.scalar(
            apply_filters(
                select(func.count(Vehicle.id)),
                filters,
                default_status="active",
            )
        ) or 0

        deact_30d = await db.scalar(
            apply_filters(
                select(func.count(Vehicle.id)),
                filters.model_copy(update={"status": "inactive"}),
            ).where(Vehicle.date_deactivated >= d30)
        ) or 0

        turnover_rate = deact_30d / active_count if active_count > 0 else None
        days_of_supply = 30.0 / turnover_rate if turnover_rate and turnover_rate > 0 else None

        # Most / least liquid make (by turnover ratio)
        make_rows = (await db.execute(
            select(
                Vehicle.make.label("make"),
                func.count().filter(Vehicle.status == "active").label("active"),
                func.count().filter(
                    Vehicle.status == "inactive",
                    Vehicle.date_deactivated >= d30,
                ).label("deact"),
            )
            .select_from(
                apply_filters(
                    select(Vehicle.make, Vehicle.status, Vehicle.date_deactivated),
                    filters.model_copy(update={"status": None}),
                ).subquery()
            )
            .group_by(Vehicle.make)
            .having(func.count().filter(Vehicle.status == "active") >= 5)
        )).all()

        most_liquid = least_liquid = None
        best_rate = -1.0
        worst_rate = float("inf")
        for r in make_rows:
            if r.active > 0:
                rate = r.deact / r.active
                if rate > best_rate:
                    best_rate = rate
                    most_liquid = r.make
                if rate < worst_rate:
                    worst_rate = rate
                    least_liquid = r.make

        return {
            "avg_active_inventory": active_count,
            "deactivated_30d": deact_30d,
            "turnover_rate": safe_round(turnover_rate, 3),
            "days_of_supply": safe_round(days_of_supply, 1),
            "most_liquid_make": most_liquid,
            "least_liquid_make": least_liquid,
        }

    return await cache_aggregate(f"liquidity/kpis:{filters.cache_key()}", 300, compute)


@router.get("/by-make")
async def liquidity_by_make(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=15, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        now = datetime.now(timezone.utc)
        d30 = now - timedelta(days=30)

        cleared = filters.model_copy(update={"status": None})
        rows = (await db.execute(
            apply_filters(
                select(
                    Vehicle.make.label("make"),
                    func.count().filter(Vehicle.status == "active").label("active"),
                    func.count().filter(
                        Vehicle.status == "inactive",
                        Vehicle.date_deactivated >= d30,
                    ).label("deact_30d"),
                ),
                cleared,
            )
            .group_by(Vehicle.make)
            .having(func.count().filter(Vehicle.status == "active") > 0)
            .order_by(
                (
                    func.count().filter(
                        Vehicle.status == "inactive",
                        Vehicle.date_deactivated >= d30,
                    ) * 1.0 / func.nullif(func.count().filter(Vehicle.status == "active"), 0)
                ).desc()
            )
            .limit(limit)
        )).all()

        result = []
        for r in rows:
            rate = r.deact_30d / r.active if r.active > 0 else None
            dos = 30.0 / rate if rate and rate > 0 else None
            result.append({
                "make": r.make,
                "active": r.active,
                "deact_30d": r.deact_30d,
                "turnover_rate": safe_round(rate, 3),
                "days_of_supply": safe_round(dos, 1),
            })
        return result

    return await cache_aggregate(
        f"liquidity/by-make:{limit}:{filters.cache_key()}", 300, compute
    )


@router.get("/by-city")
async def liquidity_by_city(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        now = datetime.now(timezone.utc)
        d30 = now - timedelta(days=30)

        cleared = filters.model_copy(update={"status": None})
        rows = (await db.execute(
            apply_filters(
                select(
                    Vehicle.city.label("city"),
                    func.count().filter(Vehicle.status == "active").label("active"),
                    func.count().filter(
                        Vehicle.status == "inactive",
                        Vehicle.date_deactivated >= d30,
                    ).label("deact_30d"),
                ),
                cleared,
            )
            .where(Vehicle.city.isnot(None))
            .group_by(Vehicle.city)
            .having(func.count().filter(Vehicle.status == "active") > 0)
            .order_by(
                (
                    func.count().filter(
                        Vehicle.status == "inactive",
                        Vehicle.date_deactivated >= d30,
                    ) * 1.0 / func.nullif(func.count().filter(Vehicle.status == "active"), 0)
                ).desc()
            )
            .limit(limit)
        )).all()

        result = []
        for r in rows:
            rate = r.deact_30d / r.active if r.active > 0 else None
            dos = 30.0 / rate if rate and rate > 0 else None
            result.append({
                "city": r.city,
                "active": r.active,
                "deact_30d": r.deact_30d,
                "turnover_rate": safe_round(rate, 3),
                "days_of_supply": safe_round(dos, 1),
            })
        return result

    return await cache_aggregate(
        f"liquidity/by-city:{limit}:{filters.cache_key()}", 300, compute
    )


@router.get("/trend")
async def liquidity_trend(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        since = datetime.now(timezone.utc) - timedelta(days=180)
        cleared = filters.model_copy(update={"status": None, "date_from": None, "date_to": None})

        add_bucket = date_trunc("month", Vehicle.date_added).label("period")
        add_rows = (await db.execute(
            apply_filters(select(add_bucket, func.count().label("added")), cleared)
            .where(Vehicle.date_added >= since)
            .group_by(add_bucket)
        )).all()

        deact_bucket = date_trunc("month", Vehicle.date_deactivated).label("period")
        deact_rows = (await db.execute(
            apply_filters(select(deact_bucket, func.count().label("deactivated")), cleared)
            .where(Vehicle.date_deactivated >= since)
            .group_by(deact_bucket)
        )).all()

        adds = {r.period.date(): r.added for r in add_rows}
        deacts = {r.period.date(): r.deactivated for r in deact_rows}
        all_periods = sorted(set(adds) | set(deacts))
        return [
            {
                "period": d.isoformat(),
                "added": adds.get(d, 0),
                "deactivated": deacts.get(d, 0),
            }
            for d in all_periods
        ]

    return await cache_aggregate(f"liquidity/trend:{filters.cache_key()}", 600, compute)


@router.get("/table")
async def liquidity_table(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        now = datetime.now(timezone.utc)
        d30 = now - timedelta(days=30)

        cleared = filters.model_copy(update={"status": None})
        rows = (await db.execute(
            apply_filters(
                select(
                    Vehicle.make.label("make"),
                    Vehicle.model.label("model"),
                    func.count().filter(Vehicle.status == "active").label("active"),
                    func.count().filter(
                        Vehicle.status == "inactive",
                        Vehicle.date_deactivated >= d30,
                    ).label("deact_30d"),
                ),
                cleared,
            )
            .group_by(Vehicle.make, Vehicle.model)
            .having(func.count().filter(Vehicle.status == "active") > 0)
            .order_by(
                (
                    func.count().filter(
                        Vehicle.status == "inactive",
                        Vehicle.date_deactivated >= d30,
                    ) * 1.0 / func.nullif(func.count().filter(Vehicle.status == "active"), 0)
                ).desc()
            )
            .limit(limit)
        )).all()

        result = []
        for r in rows:
            rate = r.deact_30d / r.active if r.active > 0 else None
            dos = 30.0 / rate if rate and rate > 0 else None
            result.append({
                "make": r.make,
                "model": r.model,
                "active": r.active,
                "deact_30d": r.deact_30d,
                "turnover_rate": safe_round(rate, 3),
                "days_of_supply": safe_round(dos, 1),
            })
        return result

    return await cache_aggregate(
        f"liquidity/table:{limit}:{filters.cache_key()}", 300, compute
    )
