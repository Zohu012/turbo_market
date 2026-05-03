"""
Dashboard — Competitor Analysis.

Seller-centric view: top sellers, type distribution, price strategies.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.seller import Seller
from app.models.vehicle import Vehicle
from app.schemas.analytics_filters import AnalyticsFilters
from app.services.analytics_cache import cache_aggregate
from app.services.analytics_filters import apply_filters
from app.services.analytics_helpers import percentile, safe_round

router = APIRouter(prefix="/competitors", tags=["analytics-competitors"])


@router.get("/kpis")
async def competitors_kpis(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        row = (await db.execute(
            apply_filters(
                select(
                    func.count(func.distinct(Vehicle.seller_id)).label("total_sellers"),
                    func.count(func.distinct(Vehicle.seller_id)).filter(
                        Seller.seller_type.in_(("business", "dealer"))
                    ).label("biz_sellers"),
                ),
                filters,
                join_seller=True,
                default_status="active",
            )
        )).one()

        # Avg listing count per seller
        seller_counts = (await db.execute(
            apply_filters(
                select(Vehicle.seller_id, func.count().label("cnt")),
                filters,
                default_status="active",
            )
            .where(Vehicle.seller_id.isnot(None))
            .group_by(Vehicle.seller_id)
        )).all()

        avg_per_seller = (
            sum(r.cnt for r in seller_counts) / len(seller_counts)
            if seller_counts else None
        )

        # Most active seller
        most_active_row = (await db.execute(
            apply_filters(
                select(
                    Seller.name.label("name"),
                    func.count(Vehicle.id).label("cnt"),
                ),
                filters,
                join_seller=True,
                default_status="active",
            )
            .where(Vehicle.seller_id.isnot(None))
            .group_by(Seller.name)
            .order_by(func.count(Vehicle.id).desc())
            .limit(1)
        )).first()

        return {
            "total_active_sellers": row.total_sellers or 0,
            "total_business_sellers": row.biz_sellers or 0,
            "avg_listings_per_seller": safe_round(avg_per_seller, 1),
            "most_active_seller": most_active_row.name if most_active_row else None,
            "most_active_seller_count": most_active_row.cnt if most_active_row else 0,
        }

    return await cache_aggregate(f"competitors/kpis:{filters.cache_key()}", 300, compute)


@router.get("/top-sellers")
async def competitors_top_sellers(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        rows = (await db.execute(
            apply_filters(
                select(
                    Seller.id.label("seller_id"),
                    Seller.name.label("name"),
                    Seller.seller_type.label("seller_type"),
                    Seller.city.label("city"),
                    Seller.total_listings.label("total_listings"),
                    Seller.total_sold.label("total_sold"),
                    Seller.avg_days_to_sell.label("avg_dts"),
                    func.count(Vehicle.id).label("active_count"),
                    func.avg(Vehicle.price_azn).label("avg_price"),
                ),
                filters,
                join_seller=True,
                default_status="active",
            )
            .where(Vehicle.seller_id.isnot(None))
            .group_by(
                Seller.id, Seller.name, Seller.seller_type,
                Seller.city, Seller.total_listings, Seller.total_sold, Seller.avg_days_to_sell,
            )
            .order_by(func.count(Vehicle.id).desc())
            .limit(limit)
            .offset(offset)
        )).all()

        total = await db.scalar(
            apply_filters(
                select(func.count(func.distinct(Vehicle.seller_id))),
                filters,
                join_seller=True,
                default_status="active",
            ).where(Vehicle.seller_id.isnot(None))
        )

        items = [
            {
                "seller_id": r.seller_id,
                "name": r.name or "—",
                "seller_type": r.seller_type or "unknown",
                "city": r.city,
                "active_count": r.active_count,
                "total_listings": r.total_listings or 0,
                "total_sold": r.total_sold or 0,
                "avg_price": safe_round(r.avg_price, 0),
                "avg_dts": safe_round(r.avg_dts, 1),
            }
            for r in rows
        ]
        return {"total": total or 0, "items": items}

    return await cache_aggregate(
        f"competitors/top-sellers:{limit}:{offset}:{filters.cache_key()}", 300, compute
    )


@router.get("/by-type")
async def competitors_by_type(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        rows = (await db.execute(
            apply_filters(
                select(
                    Seller.seller_type.label("seller_type"),
                    func.count(func.distinct(Seller.id)).label("seller_count"),
                    func.count(Vehicle.id).label("listing_count"),
                ),
                filters,
                join_seller=True,
                default_status="active",
            )
            .group_by(Seller.seller_type)
            .order_by(func.count(Vehicle.id).desc())
        )).all()

        total_listings = sum(r.listing_count for r in rows)
        return [
            {
                "seller_type": r.seller_type or "unknown",
                "seller_count": r.seller_count,
                "listing_count": r.listing_count,
                "share_pct": safe_round(r.listing_count / total_listings * 100, 1) if total_listings > 0 else None,
            }
            for r in rows
        ]

    return await cache_aggregate(f"competitors/by-type:{filters.cache_key()}", 300, compute)


@router.get("/price-strategy")
async def competitors_price_strategy(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        rows = (await db.execute(
            apply_filters(
                select(
                    Seller.seller_type.label("seller_type"),
                    func.avg(Vehicle.price_azn).label("avg_price"),
                    percentile(Vehicle.price_azn, 0.5).label("median_price"),
                    func.count().label("count"),
                ),
                filters,
                join_seller=True,
                default_status="active",
            )
            .where(Vehicle.price_azn.isnot(None))
            .group_by(Seller.seller_type)
        )).all()

        return [
            {
                "seller_type": r.seller_type or "unknown",
                "avg_price": safe_round(r.avg_price, 0),
                "median_price": safe_round(r.median_price, 0),
                "count": r.count,
            }
            for r in rows
        ]

    return await cache_aggregate(f"competitors/price-strategy:{filters.cache_key()}", 300, compute)
