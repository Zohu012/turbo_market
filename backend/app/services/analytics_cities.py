"""
Dashboard — City / Region Analysis.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.vehicle import Vehicle
from app.schemas.analytics_filters import AnalyticsFilters
from app.services.analytics_cache import cache_aggregate
from app.services.analytics_filters import apply_filters
from app.services.analytics_helpers import percentile, safe_round

router = APIRouter(prefix="/cities", tags=["analytics-cities"])


@router.get("/kpis")
async def cities_kpis(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        rows = (await db.execute(
            apply_filters(
                select(
                    Vehicle.city.label("city"),
                    func.count().label("count"),
                    percentile(Vehicle.price_azn, 0.5).label("median_price"),
                    func.avg(Vehicle.days_to_sell).label("avg_dts"),
                ),
                filters,
                default_status="active",
            )
            .where(Vehicle.city.isnot(None))
            .group_by(Vehicle.city)
            .order_by(func.count().desc())
        )).all()

        dts_rows = (await db.execute(
            apply_filters(
                select(
                    Vehicle.city.label("city"),
                    func.avg(Vehicle.days_to_sell).label("avg_dts"),
                ),
                filters.model_copy(update={"status": "inactive"}),
            )
            .where(Vehicle.city.isnot(None), Vehicle.days_to_sell.isnot(None))
            .group_by(Vehicle.city)
        )).all()

        dts_map = {r.city: float(r.avg_dts) for r in dts_rows if r.avg_dts is not None}

        most_active = rows[0].city if rows else None
        most_active_count = rows[0].count if rows else 0

        # Highest median price city
        sorted_by_price = sorted(
            [r for r in rows if r.median_price is not None],
            key=lambda r: float(r.median_price),
            reverse=True,
        )
        highest_price_city = sorted_by_price[0].city if sorted_by_price else None

        # Fastest DTS city
        fastest_dts_city = min(dts_map, key=dts_map.get) if dts_map else None
        fastest_dts_value = dts_map.get(fastest_dts_city) if fastest_dts_city else None

        return {
            "cities_tracked": len(rows),
            "most_active_city": most_active,
            "most_active_count": most_active_count,
            "highest_median_price_city": highest_price_city,
            "fastest_dts_city": fastest_dts_city,
            "fastest_dts_days": safe_round(fastest_dts_value, 1),
        }

    return await cache_aggregate(f"cities/kpis:{filters.cache_key()}", 300, compute)


@router.get("/overview")
async def cities_overview(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        active_rows = (await db.execute(
            apply_filters(
                select(
                    Vehicle.city.label("city"),
                    func.count().label("count"),
                    func.avg(Vehicle.price_azn).label("avg_price"),
                    percentile(Vehicle.price_azn, 0.5).label("median_price"),
                ),
                filters,
                default_status="active",
            )
            .where(Vehicle.city.isnot(None))
            .group_by(Vehicle.city)
            .order_by(func.count().desc())
        )).all()

        dts_rows = (await db.execute(
            apply_filters(
                select(
                    Vehicle.city.label("city"),
                    func.avg(Vehicle.days_to_sell).label("avg_dts"),
                    percentile(Vehicle.days_to_sell, 0.5).label("median_dts"),
                ),
                filters.model_copy(update={"status": "inactive"}),
            )
            .where(Vehicle.city.isnot(None), Vehicle.days_to_sell.isnot(None))
            .group_by(Vehicle.city)
        )).all()

        dts_map = {r.city: r for r in dts_rows}
        total = sum(r.count for r in active_rows)

        return [
            {
                "city": r.city,
                "active_count": r.count,
                "share_pct": safe_round(r.count / total * 100, 1) if total > 0 else None,
                "avg_price": safe_round(r.avg_price, 0),
                "median_price": safe_round(r.median_price, 0),
                "avg_dts": safe_round(dts_map[r.city].avg_dts, 1) if r.city in dts_map else None,
                "median_dts": safe_round(dts_map[r.city].median_dts, 1) if r.city in dts_map else None,
            }
            for r in active_rows
        ]

    return await cache_aggregate(f"cities/overview:{filters.cache_key()}", 300, compute)


@router.get("/price")
async def cities_price(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=15, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        rows = (await db.execute(
            apply_filters(
                select(
                    Vehicle.city.label("city"),
                    percentile(Vehicle.price_azn, 0.5).label("median"),
                    func.avg(Vehicle.price_azn).label("avg"),
                    func.count().label("count"),
                ),
                filters,
                default_status="active",
            )
            .where(Vehicle.city.isnot(None), Vehicle.price_azn.isnot(None))
            .group_by(Vehicle.city)
            .order_by(percentile(Vehicle.price_azn, 0.5).desc())
            .limit(limit)
        )).all()
        return [
            {
                "city": r.city,
                "median": safe_round(r.median, 0),
                "avg": safe_round(r.avg, 0),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(
        f"cities/price:{limit}:{filters.cache_key()}", 300, compute
    )


@router.get("/dts")
async def cities_dts(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=15, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        rows = (await db.execute(
            apply_filters(
                select(
                    Vehicle.city.label("city"),
                    func.avg(Vehicle.days_to_sell).label("avg_dts"),
                    percentile(Vehicle.days_to_sell, 0.5).label("median_dts"),
                    func.count().label("count"),
                ),
                filters.model_copy(update={"status": "inactive"}),
            )
            .where(Vehicle.city.isnot(None), Vehicle.days_to_sell.isnot(None))
            .group_by(Vehicle.city)
            .having(func.count() >= 3)
            .order_by(func.avg(Vehicle.days_to_sell).asc())
            .limit(limit)
        )).all()
        return [
            {
                "city": r.city,
                "avg_dts": safe_round(r.avg_dts, 1),
                "median_dts": safe_round(r.median_dts, 1),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(
        f"cities/dts:{limit}:{filters.cache_key()}", 300, compute
    )
