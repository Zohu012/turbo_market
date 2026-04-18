from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.seller import Seller, SellerPhone


async def get_sellers(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    seller_type: Optional[str] = None,
    city: Optional[str] = None,
    sort_by: str = "total_listings",
    sort_dir: str = "desc",
) -> tuple[list[Seller], int]:
    filters = []
    if seller_type:
        filters.append(Seller.seller_type == seller_type)
    if city:
        filters.append(func.lower(Seller.city) == city.lower())

    sort_col = getattr(Seller, sort_by, Seller.total_listings)
    order = sort_col.desc() if sort_dir == "desc" else sort_col.asc()

    count_q = select(func.count()).select_from(Seller)
    if filters:
        count_q = count_q.where(*filters)
    total = await db.scalar(count_q) or 0

    q = (
        select(Seller)
        .options(selectinload(Seller.phones))
        .order_by(order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if filters:
        q = q.where(*filters)

    result = await db.execute(q)
    return list(result.scalars().all()), total


async def get_seller(db: AsyncSession, seller_id: int) -> Optional[Seller]:
    q = (
        select(Seller)
        .where(Seller.id == seller_id)
        .options(selectinload(Seller.phones))
    )
    result = await db.execute(q)
    return result.scalar_one_or_none()
