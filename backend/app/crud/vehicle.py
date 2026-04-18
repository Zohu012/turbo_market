from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.vehicle import Vehicle, VehicleImage


async def get_vehicles(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    make: Optional[str] = None,
    model: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
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
) -> tuple[list[Vehicle], int]:
    filters = []
    if status:
        filters.append(Vehicle.status == status)
    if make:
        filters.append(func.lower(Vehicle.make) == make.lower())
    if model:
        filters.append(func.lower(Vehicle.model) == model.lower())
    if year_min:
        filters.append(Vehicle.year >= year_min)
    if year_max:
        filters.append(Vehicle.year <= year_max)
    if price_min is not None:
        filters.append(Vehicle.price_azn >= price_min)
    if price_max is not None:
        filters.append(Vehicle.price_azn <= price_max)
    if odometer_max is not None:
        filters.append(Vehicle.odometer <= odometer_max)
    if odometer_type:
        filters.append(Vehicle.odometer_type == odometer_type)
    if color:
        filters.append(func.lower(Vehicle.color) == color.lower())
    if fuel_type:
        filters.append(func.lower(Vehicle.fuel_type) == fuel_type.lower())
    if transmission:
        filters.append(func.lower(Vehicle.transmission) == transmission.lower())
    if body_type:
        filters.append(func.lower(Vehicle.body_type) == body_type.lower())
    if drive_type:
        filters.append(func.lower(Vehicle.drive_type) == drive_type.lower())
    if city:
        filters.append(func.lower(Vehicle.city) == city.lower())
    if seller_id:
        filters.append(Vehicle.seller_id == seller_id)

    # Sort
    sort_col = getattr(Vehicle, sort_by, Vehicle.date_added)
    order = sort_col.desc() if sort_dir == "desc" else sort_col.asc()

    count_q = select(func.count()).select_from(Vehicle)
    if filters:
        count_q = count_q.where(*filters)
    total = await db.scalar(count_q) or 0

    q = (
        select(Vehicle)
        .options(selectinload(Vehicle.images))
        .order_by(order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if filters:
        q = q.where(*filters)

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
            selectinload(Vehicle.seller),
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
