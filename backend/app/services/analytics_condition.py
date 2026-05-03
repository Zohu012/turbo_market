"""
Dashboard — Condition Analysis.

Compare listing count, price, and DTS across condition values.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.vehicle import Vehicle
from app.schemas.analytics_filters import AnalyticsFilters
from app.services.analytics_cache import cache_aggregate
from app.services.analytics_filters import apply_filters
from app.services.analytics_helpers import percentile, safe_round

router = APIRouter(prefix="/condition", tags=["analytics-condition"])


@router.get("/kpis")
async def condition_kpis(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        rows = (await db.execute(
            apply_filters(
                select(
                    Vehicle.condition.label("condition"),
                    func.count().label("count"),
                ),
                filters,
                default_status="active",
            )
            .where(Vehicle.condition.isnot(None))
            .group_by(Vehicle.condition)
            .order_by(func.count().desc())
        )).all()

        total = sum(r.count for r in rows)
        most_common = rows[0].condition if rows else None
        most_common_count = rows[0].count if rows else 0

        return {
            "distinct_conditions": len(rows),
            "most_common_condition": most_common,
            "most_common_count": most_common_count,
            "total_with_condition": total,
        }

    return await cache_aggregate(f"condition/kpis:{filters.cache_key()}", 300, compute)


@router.get("/overview")
async def condition_overview(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        # Active: count, price stats
        active_rows = (await db.execute(
            apply_filters(
                select(
                    Vehicle.condition.label("condition"),
                    func.count().label("count"),
                    func.avg(Vehicle.price_azn).label("avg_price"),
                    percentile(Vehicle.price_azn, 0.5).label("median_price"),
                ),
                filters,
                default_status="active",
            )
            .where(Vehicle.condition.isnot(None), Vehicle.price_azn.isnot(None))
            .group_by(Vehicle.condition)
            .order_by(func.count().desc())
        )).all()

        # Inactive: DTS stats
        dts_rows = (await db.execute(
            apply_filters(
                select(
                    Vehicle.condition.label("condition"),
                    func.avg(Vehicle.days_to_sell).label("avg_dts"),
                    percentile(Vehicle.days_to_sell, 0.5).label("median_dts"),
                ),
                filters.model_copy(update={"status": "inactive"}),
            )
            .where(Vehicle.condition.isnot(None), Vehicle.days_to_sell.isnot(None))
            .group_by(Vehicle.condition)
        )).all()

        dts_map = {r.condition: r for r in dts_rows}
        total = sum(r.count for r in active_rows)

        return [
            {
                "condition": r.condition,
                "count": r.count,
                "share_pct": safe_round(r.count / total * 100, 1) if total > 0 else None,
                "avg_price": safe_round(r.avg_price, 0),
                "median_price": safe_round(r.median_price, 0),
                "avg_dts": safe_round(dts_map[r.condition].avg_dts, 1) if r.condition in dts_map else None,
                "median_dts": safe_round(dts_map[r.condition].median_dts, 1) if r.condition in dts_map else None,
            }
            for r in active_rows
        ]

    return await cache_aggregate(f"condition/overview:{filters.cache_key()}", 300, compute)


@router.get("/price-dist")
async def condition_price_dist(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        rows = (await db.execute(
            apply_filters(
                select(
                    Vehicle.condition.label("condition"),
                    percentile(Vehicle.price_azn, 0.25).label("p25"),
                    percentile(Vehicle.price_azn, 0.5).label("median"),
                    percentile(Vehicle.price_azn, 0.75).label("p75"),
                    func.avg(Vehicle.price_azn).label("avg"),
                    func.count().label("count"),
                ),
                filters,
                default_status="active",
            )
            .where(Vehicle.condition.isnot(None), Vehicle.price_azn.isnot(None))
            .group_by(Vehicle.condition)
            .order_by(func.count().desc())
        )).all()

        return [
            {
                "condition": r.condition,
                "p25": safe_round(r.p25, 0),
                "median": safe_round(r.median, 0),
                "p75": safe_round(r.p75, 0),
                "avg": safe_round(r.avg, 0),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(f"condition/price-dist:{filters.cache_key()}", 300, compute)
