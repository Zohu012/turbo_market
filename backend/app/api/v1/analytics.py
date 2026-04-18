from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.analytics import (
    get_overview, get_price_stats, get_price_trend,
    get_best_sellers, get_days_to_sell, get_inventory_by_make
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


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
