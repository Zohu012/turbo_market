from typing import Optional
from pydantic import BaseModel


class OverviewStats(BaseModel):
    total_active: int
    total_inactive: int
    new_today: int
    sold_today: int
    avg_days_to_sell: Optional[float]
    total_vehicles: int


class PriceStats(BaseModel):
    avg: Optional[float]
    min: Optional[float]
    max: Optional[float]
    median: Optional[float]
    count: int


class TrendPoint(BaseModel):
    period: str
    avg_price: Optional[float]
    median_price: Optional[float]
    count: int


class BestSeller(BaseModel):
    make: str
    model: str
    total_sold: int
    avg_days_to_sell: Optional[float]
    avg_price_azn: Optional[float]


class DaysToSellStats(BaseModel):
    avg: Optional[float]
    median: Optional[float]
    p25: Optional[float]
    p75: Optional[float]
    count: int


class InventoryByMake(BaseModel):
    make: str
    active_count: int
    inactive_count: int
    avg_price_azn: Optional[float]
