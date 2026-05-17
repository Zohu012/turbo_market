from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator


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

    @field_validator("phones", mode="before")
    @classmethod
    def _coerce_phones(cls, v):
        if not v:
            return []
        return [p.phone if hasattr(p, "phone") else str(p) for p in v]


class SellerListResponse(BaseModel):
    items: list[SellerOut]
    total: int
    page: int
    pages: int
