"""
Analytics service — KPI queries using PostgreSQL aggregate functions.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select, text, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.schemas.analytics import (
    OverviewStats, PriceStats, TrendPoint, BestSeller, DaysToSellStats, InventoryByMake
)


async def get_overview(db: AsyncSession) -> OverviewStats:
    today = datetime.now(timezone.utc).date()
    tomorrow = today + timedelta(days=1)

    total_active = await db.scalar(
        select(func.count()).where(Vehicle.status == "active")
    )
    total_inactive = await db.scalar(
        select(func.count()).where(Vehicle.status == "inactive")
    )
    new_today = await db.scalar(
        select(func.count()).where(
            Vehicle.date_added >= today,
            Vehicle.date_added < tomorrow,
        )
    )
    sold_today = await db.scalar(
        select(func.count()).where(
            Vehicle.date_deactivated >= today,
            Vehicle.date_deactivated < tomorrow,
        )
    )
    avg_dts = await db.scalar(
        select(func.avg(text("days_to_sell"))).where(
            Vehicle.status == "inactive",
            text("days_to_sell IS NOT NULL"),
        )
    )
    return OverviewStats(
        total_active=total_active or 0,
        total_inactive=total_inactive or 0,
        new_today=new_today or 0,
        sold_today=sold_today or 0,
        avg_days_to_sell=round(float(avg_dts), 1) if avg_dts else None,
        total_vehicles=(total_active or 0) + (total_inactive or 0),
    )


async def get_price_stats(
    db: AsyncSession,
    make: Optional[str] = None,
    model: Optional[str] = None,
    year: Optional[int] = None,
    period_days: int = 30,
) -> PriceStats:
    since = datetime.now(timezone.utc) - timedelta(days=period_days)
    filters = [Vehicle.price_azn.isnot(None), Vehicle.date_added >= since]
    if make:
        filters.append(func.lower(Vehicle.make) == make.lower())
    if model:
        filters.append(func.lower(Vehicle.model) == model.lower())
    if year:
        filters.append(Vehicle.year == year)

    result = await db.execute(
        select(
            func.avg(Vehicle.price_azn),
            func.min(Vehicle.price_azn),
            func.max(Vehicle.price_azn),
            func.count(),
            func.percentile_cont(0.5).within_group(Vehicle.price_azn.asc()),
        ).where(*filters)
    )
    row = result.one()
    return PriceStats(
        avg=round(float(row[0]), 2) if row[0] else None,
        min=float(row[1]) if row[1] else None,
        max=float(row[2]) if row[2] else None,
        count=row[3] or 0,
        median=round(float(row[4]), 2) if row[4] else None,
    )


async def get_price_trend(
    db: AsyncSession,
    make: Optional[str] = None,
    model: Optional[str] = None,
    period_days: int = 90,
    interval: str = "week",
) -> list[TrendPoint]:
    since = datetime.now(timezone.utc) - timedelta(days=period_days)

    trunc_expr = {
        "day": "day",
        "week": "week",
        "month": "month",
    }.get(interval, "week")

    filters = ["price_azn IS NOT NULL", f"date_added >= '{since.isoformat()}'"]
    if make:
        filters.append(f"LOWER(make) = LOWER('{make.replace(chr(39), chr(39)*2)}')")
    if model:
        filters.append(f"LOWER(model) = LOWER('{model.replace(chr(39), chr(39)*2)}')")

    where_clause = " AND ".join(filters)
    sql = text(f"""
        SELECT
            DATE_TRUNC('{trunc_expr}', date_added)::DATE AS period,
            AVG(price_azn)::FLOAT AS avg_price,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_azn) AS median_price,
            COUNT(*) AS cnt
        FROM vehicles
        WHERE {where_clause}
        GROUP BY 1
        ORDER BY 1
    """)
    result = await db.execute(sql)
    return [
        TrendPoint(
            period=str(row.period),
            avg_price=round(row.avg_price, 2) if row.avg_price else None,
            median_price=round(float(row.median_price), 2) if row.median_price else None,
            count=row.cnt,
        )
        for row in result.fetchall()
    ]


async def get_best_sellers(
    db: AsyncSession,
    period_days: int = 90,
    limit: int = 20,
) -> list[BestSeller]:
    since = datetime.now(timezone.utc) - timedelta(days=period_days)
    sql = text("""
        SELECT
            make,
            model,
            COUNT(*) AS total_sold,
            AVG(days_to_sell)::FLOAT AS avg_days,
            AVG(price_azn)::FLOAT AS avg_price
        FROM vehicles
        WHERE status = 'inactive'
          AND date_deactivated >= :since
          AND days_to_sell IS NOT NULL
        GROUP BY make, model
        ORDER BY total_sold DESC
        LIMIT :limit
    """)
    result = await db.execute(sql, {"since": since, "limit": limit})
    return [
        BestSeller(
            make=row.make,
            model=row.model,
            total_sold=row.total_sold,
            avg_days_to_sell=round(row.avg_days, 1) if row.avg_days else None,
            avg_price_azn=round(row.avg_price, 2) if row.avg_price else None,
        )
        for row in result.fetchall()
    ]


async def get_days_to_sell(
    db: AsyncSession,
    make: Optional[str] = None,
    model: Optional[str] = None,
) -> DaysToSellStats:
    filters = ["status = 'inactive'", "days_to_sell IS NOT NULL", "days_to_sell >= 0"]
    if make:
        filters.append(f"LOWER(make) = LOWER('{make.replace(chr(39), chr(39)*2)}')")
    if model:
        filters.append(f"LOWER(model) = LOWER('{model.replace(chr(39), chr(39)*2)}')")

    where = " AND ".join(filters)
    sql = text(f"""
        SELECT
            AVG(days_to_sell)::FLOAT,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY days_to_sell) AS median,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY days_to_sell) AS p25,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY days_to_sell) AS p75,
            COUNT(*)
        FROM vehicles WHERE {where}
    """)
    result = await db.execute(sql)
    row = result.one()
    return DaysToSellStats(
        avg=round(row[0], 1) if row[0] else None,
        median=round(float(row[1]), 1) if row[1] else None,
        p25=round(float(row[2]), 1) if row[2] else None,
        p75=round(float(row[3]), 1) if row[3] else None,
        count=row[4] or 0,
    )


async def get_inventory_by_make(db: AsyncSession) -> list[InventoryByMake]:
    sql = text("""
        SELECT
            make,
            COUNT(*) FILTER (WHERE status = 'active') AS active_count,
            COUNT(*) FILTER (WHERE status = 'inactive') AS inactive_count,
            AVG(price_azn) FILTER (WHERE status = 'active')::FLOAT AS avg_price
        FROM vehicles
        GROUP BY make
        ORDER BY active_count DESC
    """)
    result = await db.execute(sql)
    return [
        InventoryByMake(
            make=row.make,
            active_count=row.active_count or 0,
            inactive_count=row.inactive_count or 0,
            avg_price_azn=round(row.avg_price, 2) if row.avg_price else None,
        )
        for row in result.fetchall()
    ]
