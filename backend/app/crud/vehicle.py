from datetime import date, datetime, time, timezone
from typing import Optional

from sqlalchemy import Numeric, cast, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.seller import Seller
from app.models.vehicle import Feature, Vehicle, VehicleFeature, VehicleImage
from app.services.analytics_helpers import days_on_market_expr


def _engine_liters_expr():
    """Engine column stores CC as integer string (e.g. '1500').
    Casts it to INTEGER for range comparisons. Returns NULL for non-numeric values.
    """
    from sqlalchemy import Integer
    return cast(
        (func.regexp_match(Vehicle.engine, r"^(\d+)$"))[1],
        Integer,
    )

# Alias used by KPI endpoint import.
_engine_cc_expr = _engine_liters_expr


async def get_vehicles(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    # --- existing filters ---
    make: Optional[str] = None,
    model: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    odometer_min: Optional[int] = None,
    odometer_max: Optional[int] = None,
    odometer_type: Optional[str] = None,
    color: Optional[str] = None,
    fuel_type: Optional[str] = None,
    transmission: Optional[str] = None,
    body_type: Optional[str] = None,
    drive_type: Optional[str] = None,
    city: Optional[str] = None,
    seller_id: Optional[int] = None,
    status: str = "active",
    sort_by: str = "date_added",
    sort_dir: str = "desc",
    # --- new filters ---
    engine_min: Optional[int] = None,
    engine_max: Optional[int] = None,
    hp_min: Optional[int] = None,
    hp_max: Optional[int] = None,
    seller_type: Optional[str] = None,
    market_for: Optional[str] = None,
    condition: Optional[str] = None,
    is_on_order: Optional[bool] = None,
    is_new: Optional[bool] = None,
    is_credit: Optional[bool] = None,
    is_barter: Optional[bool] = None,
    features: Optional[list[int]] = None,
    date_added_from: Optional[date] = None,
    date_added_to: Optional[date] = None,
    date_sold_from: Optional[date] = None,
    date_sold_to: Optional[date] = None,
    days_to_sell_min: Optional[int] = None,
    days_to_sell_max: Optional[int] = None,
) -> tuple[list[Vehicle], int]:
    clauses = []

    if status:
        clauses.append(Vehicle.status == status)
    if make:
        clauses.append(func.lower(Vehicle.make) == make.lower())
    if model:
        clauses.append(func.lower(Vehicle.model) == model.lower())
    if year_min:
        clauses.append(Vehicle.year >= year_min)
    if year_max:
        clauses.append(Vehicle.year <= year_max)
    if price_min is not None:
        clauses.append(Vehicle.price_azn >= price_min)
    if price_max is not None:
        clauses.append(Vehicle.price_azn <= price_max)
    if odometer_min is not None:
        clauses.append(Vehicle.odometer >= odometer_min)
    if odometer_max is not None:
        clauses.append(Vehicle.odometer <= odometer_max)
    if odometer_type:
        clauses.append(Vehicle.odometer_type == odometer_type)
    if color:
        clauses.append(func.lower(Vehicle.color) == color.lower())
    if fuel_type:
        clauses.append(func.lower(Vehicle.fuel_type) == fuel_type.lower())
    if transmission:
        clauses.append(func.lower(Vehicle.transmission) == transmission.lower())
    if body_type:
        clauses.append(func.lower(Vehicle.body_type) == body_type.lower())
    if drive_type:
        clauses.append(func.lower(Vehicle.drive_type) == drive_type.lower())
    if city:
        clauses.append(func.lower(Vehicle.city) == city.lower())
    if seller_id:
        clauses.append(Vehicle.seller_id == seller_id)

    # New filters
    if engine_min is not None or engine_max is not None:
        liters = _engine_liters_expr()
        if engine_min is not None:
            clauses.append(liters >= engine_min)
        if engine_max is not None:
            clauses.append(liters <= engine_max)
    if hp_min is not None:
        clauses.append(Vehicle.hp >= hp_min)
    if hp_max is not None:
        clauses.append(Vehicle.hp <= hp_max)
    if market_for:
        clauses.append(Vehicle.market_for == market_for)
    if condition:
        clauses.append(Vehicle.condition.ilike(f"%{condition}%"))
    if is_on_order is not None:
        clauses.append(Vehicle.is_on_order == is_on_order)
    if is_new is not None:
        clauses.append(Vehicle.is_new == is_new)
    if is_credit is not None:
        clauses.append(Vehicle.is_credit == is_credit)
    if is_barter is not None:
        clauses.append(Vehicle.is_barter == is_barter)
    if features:
        for fid in features:
            clauses.append(
                exists(
                    select(VehicleFeature.vehicle_id).where(
                        VehicleFeature.vehicle_id == Vehicle.id,
                        VehicleFeature.feature_id == fid,
                    )
                )
            )
    if date_added_from is not None:
        clauses.append(
            Vehicle.date_added >= datetime.combine(date_added_from, time.min, tzinfo=timezone.utc)
        )
    if date_added_to is not None:
        clauses.append(
            Vehicle.date_added < datetime.combine(date_added_to, time.max, tzinfo=timezone.utc)
        )
    if date_sold_from is not None:
        clauses.append(
            Vehicle.date_deactivated >= datetime.combine(date_sold_from, time.min, tzinfo=timezone.utc)
        )
    if date_sold_to is not None:
        clauses.append(
            Vehicle.date_deactivated < datetime.combine(date_sold_to, time.max, tzinfo=timezone.utc)
        )
    if days_to_sell_min is not None:
        clauses.append(Vehicle.days_to_sell >= days_to_sell_min)
    if days_to_sell_max is not None:
        clauses.append(Vehicle.days_to_sell <= days_to_sell_max)

    # seller_type requires a join
    needs_seller_join = bool(seller_type)

    if sort_by == "days_to_sell":
        sort_col = days_on_market_expr(Vehicle)
    else:
        sort_col = getattr(Vehicle, sort_by, Vehicle.date_added)
    order = sort_col.desc() if sort_dir == "desc" else sort_col.asc()

    base_q = select(Vehicle)
    count_q = select(func.count()).select_from(Vehicle)

    if needs_seller_join:
        base_q = base_q.join(Seller, Vehicle.seller_id == Seller.id, isouter=True)
        count_q = count_q.join(Seller, Vehicle.seller_id == Seller.id, isouter=True)
        clauses.append(Seller.seller_type == seller_type)

    if clauses:
        base_q = base_q.where(*clauses)
        count_q = count_q.where(*clauses)

    total = await db.scalar(count_q) or 0

    q = (
        base_q
        .options(
            selectinload(Vehicle.images),
            selectinload(Vehicle.seller).selectinload(Seller.phones),
        )
        .order_by(order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(q)
    vehicles = result.scalars().all()
    return list(vehicles), total


async def get_vehicle_by_turbo_id(db: AsyncSession, turbo_id: int) -> Optional[Vehicle]:
    q = (
        select(Vehicle)
        .where(Vehicle.turbo_id == turbo_id)
        .options(
            selectinload(Vehicle.images),
            selectinload(Vehicle.price_history),
            selectinload(Vehicle.seller).selectinload(Seller.phones),
        )
    )
    result = await db.execute(q)
    return result.scalar_one_or_none()


async def get_makes(db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(Vehicle.make).distinct().order_by(Vehicle.make)
    )
    return [row[0] for row in result.fetchall()]


async def get_models(db: AsyncSession, make: str) -> list[str]:
    result = await db.execute(
        select(Vehicle.model)
        .where(func.lower(Vehicle.make) == make.lower())
        .distinct()
        .order_by(Vehicle.model)
    )
    return [row[0] for row in result.fetchall()]
