"""
Single SQLAlchemy filter-applier for the analytics dashboards.

Every endpoint passes its base `select(...)` through `apply_filters()` so
filtering logic lives in exactly one place.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Optional

from sqlalchemy import Select, and_, exists, func, select

from app.models.seller import Seller
from app.models.vehicle import Vehicle, VehicleFeature
from app.schemas.analytics_filters import AnalyticsFilters


def _engine_liters_expr():
    """Postgres expression: parse first numeric token from the engine text.

    The `engine` column stores values like "1.5 L / 100 H/g / Benzin" on
    turbo.az. We extract the leading volume in liters. NULL when no match.
    Slow — only invoked when an engine_min/max filter is set.
    """
    # regexp_match returns text[]; (..)[1]::numeric pulls the first capture.
    return func.cast(
        (func.regexp_match(Vehicle.engine, r"([0-9]+\.?[0-9]*)"))[1],
        type_=__import__("sqlalchemy").Numeric(4, 2),
    )


def apply_filters(
    stmt: Select,
    filters: AnalyticsFilters,
    *,
    join_seller: bool = False,
    default_status: Optional[str] = None,
) -> Select:
    """Append WHERE clauses for every non-null filter field.

    Args:
        stmt: a SELECT statement built against `Vehicle` (with optional
            additional joins already applied).
        filters: parsed `AnalyticsFilters`.
        join_seller: when True (or when `seller_type` is filtered),
            adds a JOIN to `sellers`. Caller is responsible for not
            double-joining.
        default_status: status to apply when `filters.status` is None.
            Pass "active" for most endpoints; pass None to leave unfiltered.
    """
    clauses: list = []

    # Vehicle attributes
    if filters.make:
        clauses.append(func.lower(Vehicle.make) == filters.make.lower())
    if filters.model:
        clauses.append(func.lower(Vehicle.model) == filters.model.lower())
    if filters.year_min is not None:
        clauses.append(Vehicle.year >= filters.year_min)
    if filters.year_max is not None:
        clauses.append(Vehicle.year <= filters.year_max)
    if filters.condition:
        # condition is free text on turbo.az ("Vuruğu yoxdur, rənglənməyib").
        # Use ILIKE substring so labels partially match.
        clauses.append(Vehicle.condition.ilike(f"%{filters.condition}%"))
    if filters.body_type:
        clauses.append(Vehicle.body_type == filters.body_type)
    if filters.fuel_type:
        clauses.append(Vehicle.fuel_type == filters.fuel_type)
    if filters.transmission:
        clauses.append(Vehicle.transmission == filters.transmission)
    if filters.engine_min is not None or filters.engine_max is not None:
        liters = _engine_liters_expr()
        if filters.engine_min is not None:
            clauses.append(liters >= filters.engine_min)
        if filters.engine_max is not None:
            clauses.append(liters <= filters.engine_max)
    if filters.hp_min is not None:
        clauses.append(Vehicle.hp >= filters.hp_min)
    if filters.hp_max is not None:
        clauses.append(Vehicle.hp <= filters.hp_max)
    if filters.odometer_min is not None:
        clauses.append(Vehicle.odometer >= filters.odometer_min)
    if filters.odometer_max is not None:
        clauses.append(Vehicle.odometer <= filters.odometer_max)
    if filters.color:
        clauses.append(func.lower(Vehicle.color) == filters.color.lower())
    if filters.market_for:
        clauses.append(Vehicle.market_for == filters.market_for)
    if filters.drive_type:
        clauses.append(Vehicle.drive_type == filters.drive_type)

    # Market attributes
    if filters.city:
        clauses.append(Vehicle.city == filters.city)
    if filters.price_min is not None:
        clauses.append(Vehicle.price_azn >= filters.price_min)
    if filters.price_max is not None:
        clauses.append(Vehicle.price_azn <= filters.price_max)
    if filters.currency:
        clauses.append(Vehicle.currency == filters.currency)

    # status: explicit > default > unfiltered
    chosen_status = filters.status or default_status
    if chosen_status:
        clauses.append(Vehicle.status == chosen_status)

    if filters.date_from is not None:
        clauses.append(
            Vehicle.date_added
            >= datetime.combine(filters.date_from, time.min, tzinfo=timezone.utc)
        )
    if filters.date_to is not None:
        clauses.append(
            Vehicle.date_added
            < datetime.combine(filters.date_to, time.max, tzinfo=timezone.utc)
        )

    # Features: AND across all selected (vehicle has every requested feature)
    if filters.features:
        for fid in filters.features:
            clauses.append(
                exists(
                    select(VehicleFeature.vehicle_id)
                    .where(
                        VehicleFeature.vehicle_id == Vehicle.id,
                        VehicleFeature.feature_id == fid,
                    )
                )
            )

    # Seller-type join (only when needed)
    if filters.seller_type or join_seller:
        stmt = stmt.join(Seller, Vehicle.seller_id == Seller.id, isouter=True)
        if filters.seller_type:
            clauses.append(Seller.seller_type == filters.seller_type)

    if clauses:
        stmt = stmt.where(and_(*clauses))
    return stmt
