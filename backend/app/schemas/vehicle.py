from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class VehicleImageOut(BaseModel):
    id: int
    url: str
    position: int
    is_primary: bool

    model_config = {"from_attributes": True}


class PriceHistoryOut(BaseModel):
    id: int
    price: int
    currency: str
    price_azn: Optional[float]
    recorded_at: datetime

    model_config = {"from_attributes": True}


class VehicleSummary(BaseModel):
    id: int
    turbo_id: int
    make: str
    model: str
    year: Optional[int]
    price: Optional[int]
    currency: Optional[str]
    price_azn: Optional[float]
    odometer: Optional[int]
    odometer_type: Optional[str]
    color: Optional[str]
    engine: Optional[str]
    fuel_type: Optional[str]
    transmission: Optional[str]
    body_type: Optional[str]
    city: Optional[str]
    status: str
    date_added: datetime
    date_updated: datetime
    date_deactivated: Optional[datetime]
    days_to_sell: Optional[int]
    url: str
    primary_image: Optional[str] = None  # injected from first image

    model_config = {"from_attributes": True}


class SellerBrief(BaseModel):
    id: int
    name: Optional[str]
    seller_type: Optional[str]
    city: Optional[str]
    total_listings: int
    total_sold: int

    model_config = {"from_attributes": True}


class VehicleDetail(VehicleSummary):
    body_type: Optional[str]
    drive_type: Optional[str]
    doors: Optional[int]
    vin: Optional[str]
    description: Optional[str]
    view_count: Optional[int]
    images: list[VehicleImageOut] = []
    price_history: list[PriceHistoryOut] = []
    seller: Optional[SellerBrief] = None

    model_config = {"from_attributes": True}


class VehicleListResponse(BaseModel):
    items: list[VehicleSummary]
    total: int
    page: int
    pages: int
