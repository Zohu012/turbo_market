"""
Dashboard — Market Trends.

Long-term monthly data: price, inventory, DTS over 12-24 months.
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
from app.services.analytics_helpers import date_trunc, percentile, safe_round

router = APIRouter(prefix="/trends", tags=["analytics-trends"])


@router.get("/kpis")
async def trends_kpis(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        now = datetime.now(timezone.utc)
        cleared = filters.model_copy(update={"status": None, "date_from": None, "date_to": None})

        # Oldest data point
        oldest = await db.scalar(
            apply_filters(select(func.min(Vehicle.date_added)), cleared)
        )

        async def _median_window(start: datetime, end: datetime):
            f = cleared.model_copy(update={"date_from": start.date(), "date_to": end.date()})
            return await db.scalar(
                apply_filters(select(percentile(Vehicle.price_azn, 0.5)), f)
                .where(Vehicle.price_azn.isnot(None))
            )

        async def _active_count_window(start: datetime, end: datetime):
            f = cleared.model_copy(update={"date_from": start.date(), "date_to": end.date(), "status": "active"})
            return await db.scalar(apply_filters(select(func.count(Vehicle.id)), f)) or 0

        async def _avg_dts_window(start: datetime, end: datetime):
            f = cleared.model_copy(update={"status": "inactive"})
            return await db.scalar(
                apply_filters(select(func.avg(Vehicle.days_to_sell)), f)
                .where(Vehicle.date_deactivated >= start, Vehicle.date_deactivated < end, Vehicle.days_to_sell.isnot(None))
            )

        now_6m = now - timedelta(days=180)
        now_12m = now - timedelta(days=365)

        cur_price = await _median_window(now_6m, now)
        prev_6m_price = await _median_window(now_12m, now_6m)
        price_change_6m = ((float(cur_price) - float(prev_6m_price)) / float(prev_6m_price) * 100) if (cur_price and prev_6m_price) else None

        cur_price_12m_start = await _median_window(now_12m, now_6m)
        price_change_12m = ((float(cur_price) - float(cur_price_12m_start)) / float(cur_price_12m_start) * 100) if (cur_price and cur_price_12m_start) else None

        cur_inv = await _active_count_window(now_6m, now)
        prev_inv = await _active_count_window(now_12m, now_6m)
        inv_change_12m = ((cur_inv - prev_inv) / prev_inv * 100) if (prev_inv > 0) else None

        cur_dts = await _avg_dts_window(now_6m, now)
        prev_dts = await _avg_dts_window(now_12m, now_6m)
        dts_change_6m = ((float(cur_dts) - float(prev_dts)) / float(prev_dts) * 100) if (cur_dts and prev_dts) else None

        return {
            "oldest_data_point": oldest.date().isoformat() if oldest else None,
            "price_change_12m_pct": safe_round(price_change_12m, 1),
            "price_change_6m_pct": safe_round(price_change_6m, 1),
            "inventory_change_12m_pct": safe_round(inv_change_12m, 1),
            "dts_change_6m_pct": safe_round(dts_change_6m, 1),
        }

    return await cache_aggregate(f"trends/kpis:{filters.cache_key()}", 600, compute)


@router.get("/price")
async def trends_price(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    months: int = Query(default=24, ge=6, le=36),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        since = datetime.now(timezone.utc) - timedelta(days=months * 30)
        cleared = filters.model_copy(update={"status": None, "date_from": None, "date_to": None})
        bucket = date_trunc("month", Vehicle.date_added).label("period")
        rows = (await db.execute(
            apply_filters(
                select(
                    bucket,
                    func.avg(Vehicle.price_azn).label("avg"),
                    percentile(Vehicle.price_azn, 0.5).label("median"),
                    func.count().label("count"),
                ),
                cleared,
            )
            .where(Vehicle.date_added >= since, Vehicle.price_azn.isnot(None))
            .group_by(bucket)
            .order_by(bucket)
        )).all()
        return [
            {
                "period": r.period.date().isoformat(),
                "avg": safe_round(r.avg, 0),
                "median": safe_round(r.median, 0),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(f"trends/price:{months}:{filters.cache_key()}", 600, compute)


@router.get("/inventory")
async def trends_inventory(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    months: int = Query(default=24, ge=6, le=36),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        since = datetime.now(timezone.utc) - timedelta(days=months * 30)
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

    return await cache_aggregate(f"trends/inventory:{months}:{filters.cache_key()}", 600, compute)


@router.get("/dts")
async def trends_dts(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    months: int = Query(default=12, ge=3, le=36),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        since = datetime.now(timezone.utc) - timedelta(days=months * 30)
        cleared = filters.model_copy(update={"status": "inactive", "date_from": None, "date_to": None})
        bucket = date_trunc("month", Vehicle.date_deactivated).label("period")
        rows = (await db.execute(
            apply_filters(
                select(
                    bucket,
                    func.avg(Vehicle.days_to_sell).label("avg_dts"),
                    percentile(Vehicle.days_to_sell, 0.5).label("median_dts"),
                    func.count().label("count"),
                ),
                cleared,
            )
            .where(Vehicle.date_deactivated >= since, Vehicle.days_to_sell.isnot(None))
            .group_by(bucket)
            .order_by(bucket)
        )).all()
        return [
            {
                "period": r.period.date().isoformat(),
                "avg_dts": safe_round(r.avg_dts, 1),
                "median_dts": safe_round(r.median_dts, 1),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(f"trends/dts:{months}:{filters.cache_key()}", 600, compute)
