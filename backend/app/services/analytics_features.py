"""
Dashboard — Feature Impact.

Price premium analysis: avg price WITH vs WITHOUT each feature.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.vehicle import Feature, Vehicle, VehicleFeature
from app.schemas.analytics_filters import AnalyticsFilters
from app.services.analytics_cache import cache_aggregate
from app.services.analytics_filters import apply_filters
from app.services.analytics_helpers import safe_round

router = APIRouter(prefix="/features", tags=["analytics-features"])


@router.get("/kpis")
async def features_kpis(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    min_count: int = Query(default=10, ge=1),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        filt_sq = apply_filters(
            select(Vehicle.id, Vehicle.price_azn),
            filters,
            default_status="active",
        ).where(Vehicle.price_azn.isnot(None)).subquery()

        overall_avg = await db.scalar(
            select(func.avg(filt_sq.c.price_azn))
        ) or 0.0

        feature_rows = (await db.execute(
            select(
                Feature.name.label("name"),
                func.count(VehicleFeature.vehicle_id).label("cnt"),
                func.avg(filt_sq.c.price_azn).label("avg_with"),
            )
            .join(VehicleFeature, Feature.id == VehicleFeature.feature_id)
            .join(filt_sq, filt_sq.c.id == VehicleFeature.vehicle_id)
            .group_by(Feature.name)
            .having(func.count(VehicleFeature.vehicle_id) >= min_count)
        )).all()

        total_features = len(feature_rows)
        total_vehicles = await db.scalar(select(func.count()).select_from(filt_sq)) or 0

        # % vehicles with at least 1 feature
        vehicles_with_feature = await db.scalar(
            select(func.count(func.distinct(VehicleFeature.vehicle_id)))
            .where(VehicleFeature.vehicle_id.in_(select(filt_sq.c.id)))
        ) or 0
        pct_with_feature = vehicles_with_feature / total_vehicles if total_vehicles > 0 else None

        best_feature = None
        best_premium = None
        for r in feature_rows:
            if r.avg_with is not None:
                premium = float(r.avg_with) - float(overall_avg)
                if best_premium is None or premium > best_premium:
                    best_premium = premium
                    best_feature = r.name

        return {
            "total_features_tracked": total_features,
            "max_premium_feature": best_feature,
            "max_premium_azn": safe_round(best_premium, 0),
            "pct_vehicles_with_feature": safe_round(pct_with_feature, 3),
            "overall_avg_price": safe_round(overall_avg, 0),
        }

    return await cache_aggregate(
        f"features/kpis:{min_count}:{filters.cache_key()}", 300, compute
    )


@router.get("/impact")
async def features_impact(
    filters: AnalyticsFilters = Depends(AnalyticsFilters.as_query),
    min_count: int = Query(default=10, ge=1),
    sort_by: str = Query(default="premium_azn", pattern="^(premium_azn|premium_pct|count_with|name)$"),
    db: AsyncSession = Depends(get_db),
):
    async def compute():
        filt_sq = apply_filters(
            select(Vehicle.id, Vehicle.price_azn),
            filters,
            default_status="active",
        ).where(Vehicle.price_azn.isnot(None)).subquery()

        overall_avg = float(await db.scalar(select(func.avg(filt_sq.c.price_azn))) or 0.0)

        rows = (await db.execute(
            select(
                Feature.name.label("name"),
                func.count(VehicleFeature.vehicle_id).label("count_with"),
                func.avg(filt_sq.c.price_azn).label("avg_with"),
            )
            .join(VehicleFeature, Feature.id == VehicleFeature.feature_id)
            .join(filt_sq, filt_sq.c.id == VehicleFeature.vehicle_id)
            .group_by(Feature.name)
            .having(func.count(VehicleFeature.vehicle_id) >= min_count)
        )).all()

        result = []
        for r in rows:
            avg_with = float(r.avg_with) if r.avg_with is not None else None
            avg_without = overall_avg  # simplified: overall avg as "without" baseline
            premium_azn = round(avg_with - avg_without, 0) if avg_with is not None else None
            premium_pct = round((avg_with - avg_without) / avg_without * 100, 1) if (avg_with is not None and avg_without and avg_without > 0) else None
            result.append({
                "feature_name": r.name,
                "count_with": r.count_with,
                "avg_with": safe_round(avg_with, 0),
                "avg_without": safe_round(avg_without, 0),
                "premium_azn": premium_azn,
                "premium_pct": premium_pct,
            })

        reverse = sort_by != "name"
        key_fn = {
            "premium_azn": lambda x: (x["premium_azn"] or 0),
            "premium_pct": lambda x: (x["premium_pct"] or 0),
            "count_with": lambda x: (x["count_with"] or 0),
            "name": lambda x: x["feature_name"],
        }[sort_by]
        result.sort(key=key_fn, reverse=reverse)
        return result

    return await cache_aggregate(
        f"features/impact:{min_count}:{sort_by}:{filters.cache_key()}", 300, compute
    )
