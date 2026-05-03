"""
Dashboard — Opportunity Finder.

Active listings priced below P25 of the comparable filter set.
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
from app.services.analytics_helpers import percentile, safe_round

router = APIRouter(prefix="/opportunities", tags=["analytics-opportunities"])


def _age_expr(now: datetime):
    return func.extract(
        "epoch",
        now - func.coalesce(Vehicle.last_activated_at, Vehicle.date_added),
    ) / 86400


@router.get("/kpis")
async def opportunities_kpis(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        now = datetime.now(timezone.utc)
        d7 = now - timedelta(days=7)

        # P25 of the filter set
        p25_val = await db.scalar(
            apply_filters(
                select(percentile(Vehicle.price_azn, 0.25)),
                filters,
                default_status="active",
            ).where(Vehicle.price_azn.isnot(None))
        )
        if p25_val is None:
            return {
                "total_deals": 0,
                "market_p25": None,
                "median_discount_pct": None,
                "avg_discount_azn": None,
                "deals_last_7d": 0,
            }

        p25 = float(p25_val)

        deal_base = apply_filters(
            select(
                func.count().label("total"),
                func.avg(p25 - Vehicle.price_azn).label("avg_discount_azn"),
                percentile((p25 - Vehicle.price_azn) / p25 * 100, 0.5).label("median_disc_pct"),
                func.count().filter(Vehicle.date_added >= d7).label("last_7d"),
            ),
            filters,
            default_status="active",
        ).where(Vehicle.price_azn < p25, Vehicle.price_azn.isnot(None))

        row = (await db.execute(deal_base)).one()

        return {
            "total_deals": row.total or 0,
            "market_p25": safe_round(p25, 0),
            "median_discount_pct": safe_round(row.median_disc_pct, 1),
            "avg_discount_azn": safe_round(row.avg_discount_azn, 0),
            "deals_last_7d": row.last_7d or 0,
        }

    return await cache_aggregate(f"opportunities/kpis:{filters.cache_key()}", 300, compute)


@router.get("/listings")
async def opportunities_listings(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        now = datetime.now(timezone.utc)

        p25_val = await db.scalar(
            apply_filters(
                select(percentile(Vehicle.price_azn, 0.25)),
                filters,
                default_status="active",
            ).where(Vehicle.price_azn.isnot(None))
        )
        if p25_val is None:
            return {"total": 0, "market_p25": None, "items": []}

        p25 = float(p25_val)
        age = _age_expr(now).label("days_on_market")

        base = apply_filters(
            select(Vehicle, age),
            filters,
            default_status="active",
        ).where(Vehicle.price_azn < p25, Vehicle.price_azn.isnot(None))

        total = await db.scalar(
            apply_filters(
                select(func.count(Vehicle.id)),
                filters,
                default_status="active",
            ).where(Vehicle.price_azn < p25, Vehicle.price_azn.isnot(None))
        )

        disc_expr = ((p25 - Vehicle.price_azn) / p25 * 100)
        rows = (await db.execute(
            base.order_by(disc_expr.desc()).limit(limit).offset(offset)
        )).all()

        items = []
        for row in rows:
            v = row.Vehicle
            price = float(v.price_azn) if v.price_azn else None
            disc_azn = round(p25 - price, 0) if price is not None else None
            disc_pct = round((p25 - price) / p25 * 100, 1) if price is not None else None
            items.append({
                "id": v.id,
                "make": v.make,
                "model": v.model,
                "year": v.year,
                "price_azn": price,
                "market_p25": p25,
                "discount_azn": disc_azn,
                "discount_pct": disc_pct,
                "city": v.city,
                "url": v.url,
                "date_added": v.date_added.isoformat() if v.date_added else None,
                "days_on_market": round(float(row.days_on_market), 0) if row.days_on_market is not None else None,
            })
        return {"total": total or 0, "market_p25": safe_round(p25, 0), "items": items}

    return await cache_aggregate(
        f"opportunities/listings:{offset}:{limit}:{filters.cache_key()}", 300, compute
    )
