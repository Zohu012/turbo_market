"""
Shared filter contract for analytics dashboards.

Every analytics endpoint in v1 accepts the same query-string shape via
`Depends(AnalyticsFilters.as_query)`. The Pydantic model is also used as the
key for the Redis aggregate cache.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Optional

from fastapi import Query
from pydantic import BaseModel, Field, ConfigDict


SellerType = str  # Literal["business","dealer","private"] enforced via Query pattern
Status = str      # Literal["active","inactive"] enforced via Query pattern


class AnalyticsFilters(BaseModel):
    """All fields optional. Endpoints choose their own defaults (e.g. status).

    Caveats:
    - `engine_min/max` filter via regex on the `engine` text column. Slow.
      A v2 computed column would fix this.
    - `credit`/`barter` aren't stored as first-class columns yet; they're
      accepted but ignored in v1 unless the endpoint chooses to extract them
      from `raw_detail_json`.
    - `gears` is parsed best-effort from `engine` where present.
    """

    model_config = ConfigDict(extra="forbid")

    # --- Vehicle attributes ---
    make: Optional[str] = None
    model: Optional[str] = None
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    condition: Optional[str] = None
    body_type: Optional[str] = None
    fuel_type: Optional[str] = None
    transmission: Optional[str] = None
    gears: Optional[int] = None
    engine_min: Optional[float] = None
    engine_max: Optional[float] = None
    hp_min: Optional[int] = None
    hp_max: Optional[int] = None
    odometer_min: Optional[int] = None
    odometer_max: Optional[int] = None
    color: Optional[str] = None
    market_for: Optional[str] = None
    drive_type: Optional[str] = None

    # --- Market attributes ---
    city: Optional[str] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    currency: Optional[str] = None
    credit: Optional[bool] = None
    barter: Optional[bool] = None
    seller_type: Optional[str] = None
    status: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    features: Optional[list[int]] = Field(default=None, max_length=10)

    # ---- FastAPI Depends adapter ----
    @classmethod
    def as_query(
        cls,
        make: Optional[str] = Query(None),
        model: Optional[str] = Query(None),
        year_min: Optional[int] = Query(None, ge=1900, le=2100),
        year_max: Optional[int] = Query(None, ge=1900, le=2100),
        condition: Optional[str] = Query(None),
        body_type: Optional[str] = Query(None),
        fuel_type: Optional[str] = Query(None),
        transmission: Optional[str] = Query(None),
        gears: Optional[int] = Query(None, ge=1, le=12),
        engine_min: Optional[float] = Query(None, ge=0, le=20),
        engine_max: Optional[float] = Query(None, ge=0, le=20),
        hp_min: Optional[int] = Query(None, ge=0, le=2000),
        hp_max: Optional[int] = Query(None, ge=0, le=2000),
        odometer_min: Optional[int] = Query(None, ge=0),
        odometer_max: Optional[int] = Query(None, ge=0),
        color: Optional[str] = Query(None),
        market_for: Optional[str] = Query(None),
        drive_type: Optional[str] = Query(None),
        city: Optional[str] = Query(None),
        price_min: Optional[float] = Query(None, ge=0),
        price_max: Optional[float] = Query(None, ge=0),
        currency: Optional[str] = Query(None, max_length=3),
        credit: Optional[bool] = Query(None),
        barter: Optional[bool] = Query(None),
        seller_type: Optional[str] = Query(
            None, pattern="^(business|dealer|private)$"
        ),
        status: Optional[str] = Query(None, pattern="^(active|inactive)$"),
        date_from: Optional[date] = Query(None),
        date_to: Optional[date] = Query(None),
        features: Optional[str] = Query(
            None, description="Comma-separated feature IDs, max 10"
        ),
    ) -> "AnalyticsFilters":
        feature_ids: Optional[list[int]] = None
        if features:
            try:
                feature_ids = [int(x) for x in features.split(",") if x.strip()][:10]
            except ValueError:
                feature_ids = None
        return cls(
            make=make, model=model,
            year_min=year_min, year_max=year_max,
            condition=condition, body_type=body_type,
            fuel_type=fuel_type, transmission=transmission, gears=gears,
            engine_min=engine_min, engine_max=engine_max,
            hp_min=hp_min, hp_max=hp_max,
            odometer_min=odometer_min, odometer_max=odometer_max,
            color=color, market_for=market_for, drive_type=drive_type,
            city=city, price_min=price_min, price_max=price_max,
            currency=currency, credit=credit, barter=barter,
            seller_type=seller_type, status=status,
            date_from=date_from, date_to=date_to,
            features=feature_ids,
        )

    def cache_key(self) -> str:
        """Deterministic short hash from non-null fields. Used for Redis keys."""
        payload = {
            k: (v if not isinstance(v, date) else v.isoformat())
            for k, v in sorted(self.model_dump(exclude_none=True).items())
        }
        return hashlib.sha1(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
