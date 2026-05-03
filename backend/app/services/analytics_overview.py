"""
Dashboard 1 — Main Overview.

Endpoints under `/analytics/overview/*`. All accept the shared `AnalyticsFilters`.
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
from app.services.analytics_helpers import date_trunc, percentile, safe_round


router = APIRouter(prefix="/overview", tags=["analytics-overview"])


@router.get("/kpis")
async def overview_kpis(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    """All overview KPIs in one payload."""

    async def compute():
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        d7 = now - timedelta(days=7)
        d30 = now - timedelta(days=30)

        # Active count
        active = await db.scalar(
            apply_filters(
                select(func.count(Vehicle.id)),
                filters.model_copy(update={"status": "active"}),
            )
        ) or 0

        # New today / 7d / 30d — no status constraint, just date filter
        base_f = filters.model_copy(update={"date_from": None, "date_to": None, "status": None})
        new_today = await db.scalar(
            apply_filters(select(func.count(Vehicle.id)), base_f)
            .where(Vehicle.date_added >= today_start)
        ) or 0
        new_7d = await db.scalar(
            apply_filters(select(func.count(Vehicle.id)), base_f)
            .where(Vehicle.date_added >= d7)
        ) or 0
        new_30d = await db.scalar(
            apply_filters(select(func.count(Vehicle.id)), base_f)
            .where(Vehicle.date_added >= d30)
        ) or 0

        # Deactivated in last 30d
        deact_30d = await db.scalar(
            apply_filters(
                select(func.count(Vehicle.id)),
                base_f.model_copy(update={"status": "inactive"}),
            ).where(Vehicle.date_deactivated >= d30)
        ) or 0

        # Price stats over active
        price_row = (await db.execute(
            apply_filters(
                select(
                    percentile(Vehicle.price_azn, 0.5).label("median_price"),
                    func.avg(Vehicle.price_azn).label("avg_price"),
                ),
                filters.model_copy(update={"status": "active"}),
            ).where(Vehicle.price_azn.isnot(None))
        )).one()

        # Avg mileage
        avg_mileage = await db.scalar(
            apply_filters(
                select(func.avg(Vehicle.odometer)),
                filters.model_copy(update={"status": "active"}),
            ).where(Vehicle.odometer.isnot(None))
        )

        # DTS stats over inactive
        dts_row = (await db.execute(
            apply_filters(
                select(
                    func.avg(Vehicle.days_to_sell).label("avg_dts"),
                    percentile(Vehicle.days_to_sell, 0.5).label("median_dts"),
                ),
                filters.model_copy(update={"status": "inactive"}),
            ).where(Vehicle.days_to_sell.isnot(None))
        )).one()

        # Dealer / private share
        share_row = (await db.execute(
            apply_filters(
                select(
                    func.count().filter(Seller.seller_type.in_(("business", "dealer"))).label("dealer"),
                    func.count().filter(Seller.seller_type == "private").label("private"),
                    func.count().label("total"),
                ),
                filters,
                join_seller=True,
                default_status="active",
            )
        )).one()
        total_share = share_row.total or 0

        # Price trend 7d / 30d pct change
        async def _median_in_window(start: datetime, end: datetime) -> float | None:
            f = filters.model_copy(update={"date_from": start.date(), "date_to": end.date(), "status": None})
            return await db.scalar(
                apply_filters(select(percentile(Vehicle.price_azn, 0.5)), f)
                .where(Vehicle.price_azn.isnot(None))
            )

        try:
            cur7 = await _median_in_window(d7, now)
            prev7 = await _median_in_window(d7 - timedelta(days=7), d7)
            trend_7d = ((float(cur7) - float(prev7)) / float(prev7) * 100) if (cur7 and prev7) else None
            cur30 = await _median_in_window(d30, now)
            prev30 = await _median_in_window(d30 - timedelta(days=30), d30)
            trend_30d = ((float(cur30) - float(prev30)) / float(prev30) * 100) if (cur30 and prev30) else None
        except Exception:
            trend_7d = trend_30d = None

        # Fastest / slowest segment (last 90d, ≥5 sold)
        seg_base = (
            apply_filters(
                select(
                    Vehicle.make.label("make"),
                    Vehicle.model.label("model"),
                    func.avg(Vehicle.days_to_sell).label("avg_dts"),
                ),
                filters.model_copy(update={"status": "inactive"}),
            )
            .where(
                Vehicle.days_to_sell.isnot(None),
                Vehicle.date_deactivated >= now - timedelta(days=90),
            )
            .group_by(Vehicle.make, Vehicle.model)
            .having(func.count() >= 5)
        )
        fastest = (await db.execute(seg_base.order_by(func.avg(Vehicle.days_to_sell).asc()).limit(1))).first()
        slowest = (await db.execute(seg_base.order_by(func.avg(Vehicle.days_to_sell).desc()).limit(1))).first()

        return {
            "active": active,
            "new_today": new_today,
            "new_7d": new_7d,
            "new_30d": new_30d,
            "deactivated_30d": deact_30d,
            "median_price": safe_round(price_row.median_price, 0),
            "avg_price": safe_round(price_row.avg_price, 0),
            "avg_mileage": safe_round(avg_mileage, 0),
            "avg_dts": safe_round(dts_row.avg_dts, 1),
            "median_dts": safe_round(dts_row.median_dts, 1),
            "dealer_share": round(share_row.dealer / total_share, 3) if total_share else None,
            "private_share": round(share_row.private / total_share, 3) if total_share else None,
            "price_trend_7d_pct": safe_round(trend_7d, 1),
            "price_trend_30d_pct": safe_round(trend_30d, 1),
            "fastest_segment": (
                {"make": fastest.make, "model": fastest.model, "avg_dts": safe_round(fastest.avg_dts, 1)}
                if fastest else None
            ),
            "slowest_segment": (
                {"make": slowest.make, "model": slowest.model, "avg_dts": safe_round(slowest.avg_dts, 1)}
                if slowest else None
            ),
        }

    return await cache_aggregate(f"overview/kpis:{filters.cache_key()}", 300, compute)


@router.get("/listings-by-day")
async def listings_by_day(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """New listings per day over the last `days`."""

    async def compute():
        since = datetime.now(timezone.utc) - timedelta(days=days)
        bucket = date_trunc("day", Vehicle.date_added).label("period")
        stmt = (
            apply_filters(
                select(bucket, func.count().label("count")),
                filters.model_copy(update={"status": None}),
            )
            .where(Vehicle.date_added >= since)
            .group_by(bucket)
            .order_by(bucket)
        )
        rows = (await db.execute(stmt)).all()
        return [{"period": r.period.date().isoformat(), "count": r.count} for r in rows]

    return await cache_aggregate(
        f"overview/listings-by-day:{days}:{filters.cache_key()}", 300, compute
    )


@router.get("/active-vs-inactive-trend")
async def active_vs_inactive_trend(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Daily *flow*: new additions and deactivations per day (not stock)."""

    async def compute():
        since = datetime.now(timezone.utc) - timedelta(days=days)
        cleared = filters.model_copy(update={"status": None, "date_from": None, "date_to": None})

        add_bucket = date_trunc("day", Vehicle.date_added).label("period")
        add_stmt = (
            apply_filters(select(add_bucket, func.count().label("added")), cleared)
            .where(Vehicle.date_added >= since)
            .group_by(add_bucket)
        )

        deact_bucket = date_trunc("day", Vehicle.date_deactivated).label("period")
        deact_stmt = (
            apply_filters(select(deact_bucket, func.count().label("deactivated")), cleared)
            .where(Vehicle.date_deactivated >= since)
            .group_by(deact_bucket)
        )

        adds = {r.period.date(): r.added for r in (await db.execute(add_stmt)).all()}
        deacts = {r.period.date(): r.deactivated for r in (await db.execute(deact_stmt)).all()}
        all_days = sorted(set(adds) | set(deacts))
        return [
            {"period": d.isoformat(), "added": adds.get(d, 0), "deactivated": deacts.get(d, 0)}
            for d in all_days
        ]

    return await cache_aggregate(
        f"overview/active-vs-inactive:{days}:{filters.cache_key()}", 300, compute
    )


@router.get("/median-price-trend")
async def median_price_trend(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    days: int = Query(default=90, ge=7, le=365),
    interval: str = Query(default="week", pattern="^(day|week|month)$"),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        since = datetime.now(timezone.utc) - timedelta(days=days)
        bucket = date_trunc(interval, Vehicle.date_added).label("period")
        stmt = (
            apply_filters(select(bucket, func.avg(Vehicle.price_azn).label("avg_price"), percentile(Vehicle.price_azn, 0.5).label("median_price"), func.count().label("count")), filters)
            .where(Vehicle.date_added >= since, Vehicle.price_azn.isnot(None))
            .group_by(bucket)
            .order_by(bucket)
        )
        rows = (await db.execute(stmt)).all()
        return [
            {
                "period": r.period.date().isoformat(),
                "avg_price": safe_round(r.avg_price, 0),
                "median_price": safe_round(r.median_price, 0),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(
        f"overview/median-price-trend:{days}:{interval}:{filters.cache_key()}", 600, compute
    )


@router.get("/dts-trend")
async def dts_trend(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    days: int = Query(default=180, ge=7, le=365),
    interval: str = Query(default="week", pattern="^(day|week|month)$"),
    db: AsyncSession = Depends(get_db),
):
    """Median DTS by deactivation interval."""

    async def compute():
        since = datetime.now(timezone.utc) - timedelta(days=days)
        bucket = date_trunc(interval, Vehicle.date_deactivated).label("period")
        stmt = (
            apply_filters(
                select(
                    bucket,
                    percentile(Vehicle.days_to_sell, 0.5).label("median_dts"),
                    func.avg(Vehicle.days_to_sell).label("avg_dts"),
                    func.count().label("count"),
                ),
                filters.model_copy(update={"status": "inactive"}),
            )
            .where(Vehicle.date_deactivated >= since, Vehicle.days_to_sell.isnot(None))
            .group_by(bucket)
            .order_by(bucket)
        )
        rows = (await db.execute(stmt)).all()
        return [
            {
                "period": r.period.date().isoformat(),
                "median_dts": safe_round(r.median_dts, 1),
                "avg_dts": safe_round(r.avg_dts, 1),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(
        f"overview/dts-trend:{days}:{interval}:{filters.cache_key()}", 600, compute
    )


@router.get("/listings-by-city")
async def listings_by_city(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        stmt = (
            apply_filters(
                select(Vehicle.city.label("city"), func.count().label("count")),
                filters,
                default_status="active",
            )
            .where(Vehicle.city.isnot(None))
            .group_by(Vehicle.city)
            .order_by(func.count().desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).all()
        return [{"city": r.city, "count": r.count} for r in rows]

    return await cache_aggregate(
        f"overview/listings-by-city:{limit}:{filters.cache_key()}", 300, compute
    )


@router.get("/listings-by-make")
async def listings_by_make_filtered(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=15, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Like the legacy `/inventory-by-make`, but accepts global filters."""

    async def compute():
        cleared = filters.model_copy(update={"status": None})
        stmt = (
            apply_filters(
                select(
                    Vehicle.make.label("make"),
                    func.count().filter(Vehicle.status == "active").label("active_count"),
                    func.count().filter(Vehicle.status == "inactive").label("inactive_count"),
                    func.avg(Vehicle.price_azn).filter(Vehicle.status == "active").label("avg_price"),
                ),
                cleared,
            )
            .group_by(Vehicle.make)
            .order_by(func.count().filter(Vehicle.status == "active").desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).all()
        return [
            {
                "make": r.make,
                "active_count": r.active_count or 0,
                "inactive_count": r.inactive_count or 0,
                "avg_price_azn": safe_round(r.avg_price, 0),
            }
            for r in rows
        ]

    return await cache_aggregate(
        f"overview/listings-by-make:{limit}:{filters.cache_key()}", 300, compute
    )


@router.get("/seller-type-split")
async def seller_type_split(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        stmt = (
            apply_filters(
                select(Seller.seller_type.label("seller_type"), func.count().label("count")),
                filters,
                join_seller=True,
                default_status="active",
            )
            .group_by(Seller.seller_type)
        )
        rows = (await db.execute(stmt)).all()
        total = sum(r.count for r in rows)
        return [
            {
                "seller_type": r.seller_type or "unknown",
                "count": r.count,
                "share": round(r.count / total, 3) if total else 0,
            }
            for r in rows
        ]

    return await cache_aggregate(
        f"overview/seller-split:{filters.cache_key()}", 300, compute
    )
