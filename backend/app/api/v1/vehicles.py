import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.crud.vehicle import get_vehicles, get_vehicle_by_turbo_id, get_makes, get_models
from app.models.vehicle import Feature, Vehicle
from app.schemas.vehicle import VehicleListResponse, VehicleSummary, VehicleDetail
from app.services.analytics_helpers import percentile, safe_round

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


# ---------------------------------------------------------------------------
# Shared param extraction helper (avoids repeating 30 params in two endpoints)
# ---------------------------------------------------------------------------
def _vehicle_filter_params(
    make: Optional[str] = None,
    model: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    odometer_min: Optional[int] = Query(None, ge=0),
    odometer_max: Optional[int] = Query(None, ge=0),
    odometer_type: Optional[str] = None,
    color: Optional[str] = None,
    fuel_type: Optional[str] = None,
    transmission: Optional[str] = None,
    body_type: Optional[str] = None,
    drive_type: Optional[str] = None,
    city: Optional[str] = None,
    seller_id: Optional[int] = None,
    status: str = "active",
    engine_min: Optional[int] = Query(None, ge=0, le=10000),
    engine_max: Optional[int] = Query(None, ge=0, le=10000),
    hp_min: Optional[int] = Query(None, ge=0, le=2000),
    hp_max: Optional[int] = Query(None, ge=0, le=2000),
    seller_type: Optional[str] = Query(None, pattern="^(business|dealer|private)$"),
    market_for: Optional[str] = None,
    condition: Optional[str] = None,
    is_on_order: Optional[bool] = None,
    is_new: Optional[bool] = None,
    is_credit: Optional[bool] = None,
    is_barter: Optional[bool] = None,
    features: Optional[str] = Query(None, description="Comma-separated feature IDs, max 10"),
    date_added_from: Optional[date] = None,
    date_added_to: Optional[date] = None,
    date_sold_from: Optional[date] = None,
    date_sold_to: Optional[date] = None,
    days_to_sell_min: Optional[int] = Query(None, ge=0),
    days_to_sell_max: Optional[int] = Query(None, ge=0),
) -> dict:
    feature_ids: Optional[list[int]] = None
    if features:
        try:
            feature_ids = [int(x) for x in features.split(",") if x.strip()][:10]
        except ValueError:
            feature_ids = None
    return dict(
        make=make, model=model, year_min=year_min, year_max=year_max,
        price_min=price_min, price_max=price_max,
        odometer_min=odometer_min, odometer_max=odometer_max, odometer_type=odometer_type,
        color=color, fuel_type=fuel_type, transmission=transmission,
        body_type=body_type, drive_type=drive_type, city=city, seller_id=seller_id,
        status=status,
        engine_min=engine_min, engine_max=engine_max,
        hp_min=hp_min, hp_max=hp_max,
        seller_type=seller_type, market_for=market_for, condition=condition,
        is_on_order=is_on_order, is_new=is_new, is_credit=is_credit, is_barter=is_barter,
        features=feature_ids,
        date_added_from=date_added_from, date_added_to=date_added_to,
        date_sold_from=date_sold_from, date_sold_to=date_sold_to,
        days_to_sell_min=days_to_sell_min, days_to_sell_max=days_to_sell_max,
    )


@router.get("", response_model=VehicleListResponse)
async def list_vehicles(
    filter_params: dict = Depends(_vehicle_filter_params),
    sort_by: str = "date_added",
    sort_dir: str = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    vehicles, total = await get_vehicles(
        db,
        page=page, page_size=page_size,
        sort_by=sort_by, sort_dir=sort_dir,
        **filter_params,
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


@router.get("/kpis")
async def vehicle_kpis(
    filter_params: dict = Depends(_vehicle_filter_params),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate KPIs for the current filter set."""
    from app.crud.vehicle import get_vehicles as _gv

    # We need raw access to build aggregation queries with the same filters.
    # Build filter clauses by calling get_vehicles with page_size=0 trick —
    # instead, we replicate the filter logic via a minimal inline query approach
    # using the existing CRUD which already supports all params.
    # For aggregates we query Vehicle directly.
    from app.crud.vehicle import _engine_liters_expr
    from app.models.seller import Seller
    from app.models.vehicle import VehicleFeature
    from sqlalchemy import exists, Numeric, cast
    from datetime import time
    from app.services.analytics_helpers import days_on_market_expr, percentile, safe_round

    now = datetime.now(timezone.utc)
    d7 = now - timedelta(days=7)
    d30 = now - timedelta(days=30)

    def _build_clauses(fp: dict) -> tuple[list, bool]:
        """Return (clauses_list, needs_seller_join) from filter_params dict."""
        clauses = []
        needs_seller = False
        status = fp.get("status", "active")
        if status:
            clauses.append(Vehicle.status == status)
        if fp.get("make"):
            clauses.append(func.lower(Vehicle.make) == fp["make"].lower())
        if fp.get("model"):
            clauses.append(func.lower(Vehicle.model) == fp["model"].lower())
        if fp.get("year_min"):
            clauses.append(Vehicle.year >= fp["year_min"])
        if fp.get("year_max"):
            clauses.append(Vehicle.year <= fp["year_max"])
        if fp.get("price_min") is not None:
            clauses.append(Vehicle.price_azn >= fp["price_min"])
        if fp.get("price_max") is not None:
            clauses.append(Vehicle.price_azn <= fp["price_max"])
        if fp.get("odometer_min") is not None:
            clauses.append(Vehicle.odometer >= fp["odometer_min"])
        if fp.get("odometer_max") is not None:
            clauses.append(Vehicle.odometer <= fp["odometer_max"])
        if fp.get("odometer_type"):
            clauses.append(Vehicle.odometer_type == fp["odometer_type"])
        if fp.get("color"):
            clauses.append(func.lower(Vehicle.color) == fp["color"].lower())
        if fp.get("fuel_type"):
            clauses.append(func.lower(Vehicle.fuel_type) == fp["fuel_type"].lower())
        if fp.get("transmission"):
            clauses.append(func.lower(Vehicle.transmission) == fp["transmission"].lower())
        if fp.get("body_type"):
            clauses.append(func.lower(Vehicle.body_type) == fp["body_type"].lower())
        if fp.get("drive_type"):
            clauses.append(func.lower(Vehicle.drive_type) == fp["drive_type"].lower())
        if fp.get("city"):
            clauses.append(func.lower(Vehicle.city) == fp["city"].lower())
        if fp.get("seller_id"):
            clauses.append(Vehicle.seller_id == fp["seller_id"])
        if fp.get("engine_min") is not None or fp.get("engine_max") is not None:
            liters = _engine_liters_expr()
            if fp.get("engine_min") is not None:
                clauses.append(liters >= fp["engine_min"])
            if fp.get("engine_max") is not None:
                clauses.append(liters <= fp["engine_max"])
        if fp.get("hp_min") is not None:
            clauses.append(Vehicle.hp >= fp["hp_min"])
        if fp.get("hp_max") is not None:
            clauses.append(Vehicle.hp <= fp["hp_max"])
        if fp.get("market_for"):
            clauses.append(Vehicle.market_for == fp["market_for"])
        if fp.get("condition"):
            clauses.append(Vehicle.condition.ilike(f"%{fp['condition']}%"))
        if fp.get("is_on_order") is not None:
            clauses.append(Vehicle.is_on_order == fp["is_on_order"])
        if fp.get("is_new") is not None:
            clauses.append(Vehicle.is_new == fp["is_new"])
        if fp.get("is_credit") is not None:
            clauses.append(Vehicle.is_credit == fp["is_credit"])
        if fp.get("is_barter") is not None:
            clauses.append(Vehicle.is_barter == fp["is_barter"])
        if fp.get("features"):
            for fid in fp["features"]:
                clauses.append(
                    exists(
                        select(VehicleFeature.vehicle_id).where(
                            VehicleFeature.vehicle_id == Vehicle.id,
                            VehicleFeature.feature_id == fid,
                        )
                    )
                )
        if fp.get("date_added_from") is not None:
            clauses.append(
                Vehicle.date_added >= datetime.combine(fp["date_added_from"], time.min, tzinfo=timezone.utc)
            )
        if fp.get("date_added_to") is not None:
            clauses.append(
                Vehicle.date_added < datetime.combine(fp["date_added_to"], time.max, tzinfo=timezone.utc)
            )
        if fp.get("date_sold_from") is not None:
            clauses.append(
                Vehicle.date_deactivated >= datetime.combine(fp["date_sold_from"], time.min, tzinfo=timezone.utc)
            )
        if fp.get("date_sold_to") is not None:
            clauses.append(
                Vehicle.date_deactivated < datetime.combine(fp["date_sold_to"], time.max, tzinfo=timezone.utc)
            )
        if fp.get("days_to_sell_min") is not None:
            clauses.append(Vehicle.days_to_sell >= fp["days_to_sell_min"])
        if fp.get("days_to_sell_max") is not None:
            clauses.append(Vehicle.days_to_sell <= fp["days_to_sell_max"])
        if fp.get("seller_type"):
            needs_seller = True
            clauses.append(Seller.seller_type == fp["seller_type"])
        return clauses, needs_seller

    clauses, needs_seller = _build_clauses(filter_params)

    def _apply(stmt):
        if needs_seller:
            stmt = stmt.join(Seller, Vehicle.seller_id == Seller.id, isouter=True)
        if clauses:
            stmt = stmt.where(*clauses)
        return stmt

    # Price + DTS aggregates
    agg_row = (await db.execute(
        _apply(select(
            func.avg(Vehicle.price_azn).label("avg_price"),
            percentile(Vehicle.price_azn, 0.5).label("median_price"),
            func.min(Vehicle.price_azn).label("min_price"),
            func.max(Vehicle.price_azn).label("max_price"),
            func.avg(days_on_market_expr(Vehicle)).label("avg_dts"),
            percentile(days_on_market_expr(Vehicle), 0.5).label("median_dts"),
            func.min(days_on_market_expr(Vehicle)).label("min_dts"),
            func.max(days_on_market_expr(Vehicle)).label("max_dts"),
        ))
    )).one()

    # Sales in last 7 / 30 days (inactive, date_deactivated within window)
    inactive_clauses, inactive_needs_seller = _build_clauses({
        **filter_params, "status": "inactive"
    })

    def _apply_inactive(stmt):
        if inactive_needs_seller:
            stmt = stmt.join(Seller, Vehicle.seller_id == Seller.id, isouter=True)
        if inactive_clauses:
            stmt = stmt.where(*inactive_clauses)
        return stmt

    sales_7d = await db.scalar(
        _apply_inactive(select(func.count(Vehicle.id)))
        .where(Vehicle.date_deactivated >= d7)
    ) or 0

    sales_30d = await db.scalar(
        _apply_inactive(select(func.count(Vehicle.id)))
        .where(Vehicle.date_deactivated >= d30)
    ) or 0

    # Active / sold totals (override status in clauses)
    active_clauses, active_needs_seller = _build_clauses({
        **filter_params, "status": "active"
    })
    def _apply_active(stmt):
        if active_needs_seller:
            stmt = stmt.join(Seller, Vehicle.seller_id == Seller.id, isouter=True)
        if active_clauses:
            stmt = stmt.where(*active_clauses)
        return stmt

    total_active = await db.scalar(_apply_active(select(func.count(Vehicle.id)))) or 0
    total_sold = await db.scalar(_apply_inactive(select(func.count(Vehicle.id)))) or 0

    return {
        "avg_price": safe_round(agg_row.avg_price, 0),
        "median_price": safe_round(agg_row.median_price, 0),
        "min_price": safe_round(agg_row.min_price, 0),
        "max_price": safe_round(agg_row.max_price, 0),
        "avg_dts": safe_round(agg_row.avg_dts, 1),
        "median_dts": safe_round(agg_row.median_dts, 1),
        "min_dts": agg_row.min_dts,
        "max_dts": agg_row.max_dts,
        "sales_7d": sales_7d,
        "sales_30d": sales_30d,
        "total_active": total_active,
        "total_sold": total_sold,
    }


@router.get("/features")
async def list_features(db: AsyncSession = Depends(get_db)):
    """Return all feature names with their IDs for the filter checklist."""
    result = await db.execute(select(Feature).order_by(Feature.name))
    return [{"id": f.id, "name": f.name} for f in result.scalars()]


@router.get("/makes")
async def list_makes(db: AsyncSession = Depends(get_db)):
    return {"makes": await get_makes(db)}


@router.get("/models")
async def list_models(make: str, db: AsyncSession = Depends(get_db)):
    return {"models": await get_models(db, make)}


@router.get("/years")
async def list_years(db: AsyncSession = Depends(get_db)):
    """Distinct vehicle years sorted descending."""
    result = await db.execute(
        select(Vehicle.year).distinct()
        .where(Vehicle.year.isnot(None))
        .order_by(Vehicle.year.desc())
    )
    return [r[0] for r in result.all()]


_GARBAGE_RE = r".*(null|json|undefined|N/A).*"


@router.get("/colors")
async def list_colors(db: AsyncSession = Depends(get_db)):
    """Distinct color values, garbage-filtered, sorted alphabetically."""
    result = await db.execute(
        select(Vehicle.color).distinct()
        .where(
            Vehicle.color.isnot(None),
            Vehicle.color != "",
            ~Vehicle.color.op("~*")(_GARBAGE_RE),
        )
        .order_by(Vehicle.color)
    )
    return [r[0] for r in result.all()]


@router.get("/conditions")
async def list_conditions(db: AsyncSession = Depends(get_db)):
    """Distinct condition values, garbage-filtered, sorted alphabetically."""
    result = await db.execute(
        select(Vehicle.condition).distinct()
        .where(
            Vehicle.condition.isnot(None),
            Vehicle.condition != "",
            ~Vehicle.condition.op("~*")(_GARBAGE_RE),
        )
        .order_by(Vehicle.condition)
    )
    return [r[0] for r in result.all()]


@router.get("/market-options")
async def list_market_options(db: AsyncSession = Depends(get_db)):
    """Distinct market_for values, garbage-filtered, sorted alphabetically."""
    result = await db.execute(
        select(Vehicle.market_for).distinct()
        .where(
            Vehicle.market_for.isnot(None),
            Vehicle.market_for != "",
            ~Vehicle.market_for.op("~*")(_GARBAGE_RE),
        )
        .order_by(Vehicle.market_for)
    )
    return [r[0] for r in result.all()]


@router.get("/cities")
async def list_cities(db: AsyncSession = Depends(get_db)):
    """Distinct city values, garbage-filtered, sorted alphabetically."""
    result = await db.execute(
        select(Vehicle.city).distinct()
        .where(
            Vehicle.city.isnot(None),
            Vehicle.city != "",
            ~Vehicle.city.op("~*")(_GARBAGE_RE),
        )
        .order_by(Vehicle.city)
    )
    return [r[0] for r in result.all()]


@router.get("/engine-options")
async def list_engine_options(db: AsyncSession = Depends(get_db)):
    """Distinct engine CC values (numeric only) sorted ascending."""
    from sqlalchemy import Integer
    result = await db.execute(
        select(Vehicle.engine).distinct()
        .where(
            Vehicle.engine.isnot(None),
            Vehicle.engine != "",
            Vehicle.engine.op("~")(r"^\d+$"),
        )
        .order_by(cast(Vehicle.engine, Integer))
    )
    return [r[0] for r in result.all()]


@router.get("/{turbo_id}", response_model=VehicleDetail)
async def get_vehicle(turbo_id: int, db: AsyncSession = Depends(get_db)):
    vehicle = await get_vehicle_by_turbo_id(db, turbo_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle
