"""
Session-scoped candidate-set queries for the staged daily-refresh flow.

Staged flow recap:
  Phase 1  listing scan → upsert_listing stamps every sighted card with
           `last_seen_at = session_start` (and returns `needs_detail=True`
           for new + bumped rows; the caller collects those IDs inline).
  Phase 2  (this module) identifies delist-suspects by SQL alone — rows that
           are still `active` but whose last_seen_at is older than the
           session's start, meaning they were absent from Phase 1.
  Phase 3  single detail-fetch loop over new ∪ bumped ∪ delist_suspects.
  Phase 4  safety sweep — any suspect whose detail came back not-delisted
           bumps `missing_scan_count`; bulk deactivate at >= 2.

The `target_make` filter is a scope guard: when run_local.py runs with
--make X, only vehicles of that make should be eligible for classification
as suspects. Without the guard, a make-scoped partial scan would mark every
out-of-scope vehicle as a suspect, which is wrong.
"""
import logging
from datetime import datetime
from typing import Optional

import psycopg2.extras
from psycopg2.extensions import connection as PGConnection

log = logging.getLogger(__name__)


def select_delist_suspects(
    conn: PGConnection,
    session_start: datetime,
    target_make: Optional[str] = None,
) -> list[tuple[int, str]]:
    """Active vehicles whose last_seen_at is older than this session's start.

    These are cards that did NOT appear in the current Phase 1 listing scan
    — either they've been delisted (sold), or turbo.az's search index had a
    transient hiccup. Phase 3 fetches their detail pages to resolve which.

    Returns: [(vehicle_id, url), ...] ordered by id for deterministic runs.

    Scope-safe: if target_make is provided, restricts the query to that make
    so out-of-scope rows don't get flagged during partial (--make) scans.
    """
    sql = (
        "SELECT id, url FROM vehicles "
        "WHERE status = 'active' AND last_seen_at < %s"
    )
    params: list = [session_start]
    if target_make:
        sql += " AND LOWER(make) = LOWER(%s)"
        params.append(target_make)
    sql += " ORDER BY id"

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [(r["id"], r["url"]) for r in rows]
