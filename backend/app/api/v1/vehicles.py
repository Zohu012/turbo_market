import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.crud.vehicle import get_vehicles, get_vehicle_by_turbo_id, get_makes, get_models
from app.schemas.vehicle import VehicleListResponse, VehicleSummary, VehicleDetail

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.get("", response_model=VehicleListResponse)
async def list_vehicles(
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
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    vehicles, total = await get_vehicles(
        db,
        page=page, page_size=page_size,
        make=make, model=model,
        year_min=year_min, year_max=year_max,
        price_min=price_min, price_max=price_max,
        odometer_max=odometer_max, odometer_type=odometer_type,
        color=color, fuel_type=fuel_type, transmission=transmission,
        body_type=body_type, drive_type=drive_type,
        city=city, seller_id=seller_id,
        status=status, sort_by=sort_by, sort_dir=sort_dir,
    )

    items = []
    for v in vehicles:
        summary = VehicleSummary.model_validate(v)
        summary.primary_image = v.images[0].url if v.images else None
        items.append(summary)

    return VehicleListResponse(
        items=items,
        total=total,
        page=page,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/makes")
async def list_makes(db: AsyncSession = Depends(get_db)):
    return {"makes": await get_makes(db)}


@router.get("/models")
async def list_models(make: str, db: AsyncSession = Depends(get_db)):
    return {"models": await get_models(db, make)}


@router.get("/{turbo_id}", response_model=VehicleDetail)
async def get_vehicle(turbo_id: int, db: AsyncSession = Depends(get_db)):
    vehicle = await get_vehicle_by_turbo_id(db, turbo_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle
