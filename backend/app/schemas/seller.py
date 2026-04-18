from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class SellerOut(BaseModel):
    id: int
    turbo_seller_id: Optional[str]
    name: Optional[str]
    seller_type: Optional[str]
    city: Optional[str]
    profile_url: Optional[str]
    first_seen: datetime
    last_seen: datetime
    total_listings: int
    total_sold: int
    avg_days_to_sell: Optional[float]
    phones: list[str] = []

    model_config = {"from_attributes": True}


class SellerListResponse(BaseModel):
    items: list[SellerOut]
    total: int
    page: int
    pages: int
