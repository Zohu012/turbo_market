import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.crud.seller import get_sellers, get_seller
from app.crud.vehicle import get_vehicles
from app.schemas.seller import SellerOut, SellerListResponse
from app.schemas.vehicle import VehicleListResponse, VehicleSummary

router = APIRouter(prefix="/sellers", tags=["sellers"])


@router.get("", response_model=SellerListResponse)
async def list_sellers(
    seller_type: Optional[str] = None,
    city: Optional[str] = None,
    sort_by: str = "total_listings",
    sort_dir: str = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    sellers, total = await get_sellers(
        db, page=page, page_size=page_size,
        seller_type=seller_type, city=city,
        sort_by=sort_by, sort_dir=sort_dir,
    )
    items = []
    for s in sellers:
        out = SellerOut.model_validate(s)
        out.phones = [p.phone for p in s.phones]
        items.append(out)

    return SellerListResponse(
        items=items, total=total, page=page,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{seller_id}", response_model=SellerOut)
async def get_seller_detail(seller_id: int, db: AsyncSession = Depends(get_db)):
    seller = await get_seller(db, seller_id)
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")
    out = SellerOut.model_validate(seller)
    out.phones = [p.phone for p in seller.phones]
    return out


@router.get("/{seller_id}/vehicles", response_model=VehicleListResponse)
async def seller_vehicles(
    seller_id: int,
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    vehicles, total = await get_vehicles(
        db, page=page, page_size=page_size,
        seller_id=seller_id, status=status or "active",
    )
    items = []
    for v in vehicles:
        s = VehicleSummary.model_validate(v)
        s.primary_image = v.images[0].url if v.images else None
        items.append(s)
    return VehicleListResponse(
        items=items, total=total, page=page,
        pages=math.ceil(total / page_size) if total else 0,
    )
