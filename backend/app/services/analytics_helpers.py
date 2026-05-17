"""
Postgres-specific aggregate helpers shared by the analytics dashboards.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import ColumnElement, Integer, Numeric, cast, func


def percentile(col: ColumnElement, p: float) -> ColumnElement:
    """`PERCENTILE_CONT(p) WITHIN GROUP (ORDER BY col)` — continuous percentile."""
    return func.percentile_cont(p).within_group(col.asc())


def width_bucket(
    col: ColumnElement, lo: float, hi: float, n_buckets: int
) -> ColumnElement:
    """Postgres width_bucket → 1..n_buckets, plus 0 (below lo) / n_buckets+1 (above hi)."""
    return func.width_bucket(col, lo, hi, n_buckets)


def date_trunc(interval: str, col: ColumnElement) -> ColumnElement:
    """Truncate timestamp to a calendar bucket. interval ∈ {day,week,month,year}."""
    if interval not in {"day", "week", "month", "year"}:
        raise ValueError(f"Unsupported interval: {interval!r}")
    return func.date_trunc(interval, col)


def safe_float(v) -> Optional[float]:
    return float(v) if v is not None else None


def safe_round(v, ndigits: int = 2) -> Optional[float]:
    return round(float(v), ndigits) if v is not None else None


def days_on_market_expr(vehicle_cls) -> ColumnElement:
    """FLOOR((COALESCE(date_deactivated, NOW()) - date_added) / 86400 seconds).

    Returns integer days. For sold vehicles this equals date_deactivated - date_added.
    For active vehicles it returns the current age on the market.
    Replaces the stored days_to_sell column whose value was accumulated active days.
    """
    return func.floor(
        func.extract(
            "epoch",
            func.coalesce(vehicle_cls.date_deactivated, func.now()) - vehicle_cls.date_added,
        )
        / 86400
    ).cast(Integer)
