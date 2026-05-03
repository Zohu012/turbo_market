from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.vehicle import Vehicle
from app.schemas.analytics_filters import AnalyticsFilters
from app.services.analytics import (
    get_overview, get_price_stats, get_price_trend,
    get_best_sellers, get_days_to_sell, get_inventory_by_make
)
from app.services.analytics_filters import apply_filters
from app.services.analytics_overview import router as overview_router
from app.services.analytics_price import router as price_router
from app.services.analytics_dts import router as dts_router
from app.services.analytics_makemodel import router as makemodel_router

router = APIRouter(prefix="/analytics", tags=["analytics"])


# ---------- Legacy v1 endpoints (kept for backwards compat) ----------

@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db)):
    return await get_overview(db)


@router.get("/prices")
async def prices(
    make: Optional[str] = None,
    model: Optional[str] = None,
    year: Optional[int] = None,
    period: int = Query(default=30, description="Days back"),
    db: AsyncSession = Depends(get_db),
):
    return await get_price_stats(db, make=make, model=model, year=year, period_days=period)


@router.get("/price-trend")
async def price_trend(
    make: Optional[str] = None,
    model: Optional[str] = None,
    period: int = Query(default=90),
    interval: str = Query(default="week", pattern="^(day|week|month)$"),
    db: AsyncSession = Depends(get_db),
):
    return await get_price_trend(db, make=make, model=model, period_days=period, interval=interval)


@router.get("/best-sellers")
async def best_sellers(
    period: int = Query(default=90),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await get_best_sellers(db, period_days=period, limit=limit)


@router.get("/days-to-sell")
async def days_to_sell(
    make: Optional[str] = None,
    model: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    return await get_days_to_sell(db, make=make, model=model)


@router.get("/inventory-by-make")
async def inventory_by_make(db: AsyncSession = Depends(get_db)):
    return await get_inventory_by_make(db)


# ---------- v1 dashboards: unified filter contract ----------

@router.get("/_smoke")
async def smoke(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    """Validates the AnalyticsFilters + apply_filters pipeline end-to-end."""
    stmt = apply_filters(select(func.count(Vehicle.id)), filters)
    count = await db.scalar(stmt)
    return {
        "count": count or 0,
        "cache_key": filters.cache_key(),
        "applied_filters": filters.model_dump(exclude_none=True),
    }


router.include_router(overview_router)
router.include_router(price_router)
router.include_router(dts_router)
router.include_router(makemodel_router)
