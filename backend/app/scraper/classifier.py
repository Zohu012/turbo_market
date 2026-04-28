"""
Session-scoped candidate-set queries for the staged listing → details flow.

Listing pass (run_local.py --listing-full / --listing-make):
  1. Scrape listing pages → upsert_listing stamps every sighted card with
     `last_seen_at = session_start` (and sets needs_detail_refresh=TRUE on
     new + reactivated + date_updated_turbo-bumped rows).
  2. (this module) classify delist-suspects: active rows whose last_seen_at
     is older than session_start → set needs_detail_refresh=TRUE so the
     next Details Update fetches them and confirms delisted.
  3. Two-miss safety sweep — bump missing_scan_count for every suspect,
     bulk-deactivate at >= 2.

Details Update (run_local.py --details-update) drains the
needs_detail_refresh=TRUE queue, calls mark_delisted on detail-page-confirmed
delistings and update_vehicle_detail on live ones, then clears the flag.

Scope guard: when target_make is provided, only that make is eligible for
classification — partial scans must not flag out-of-scope vehicles.
"""
import logging
from datetime import datetime
from typing import Optional, Sequence

import psycopg2.extras
from psycopg2.extensions import connection as PGConnection

log = logging.getLogger(__name__)


def select_delist_suspects(
    conn: PGConnection,
    session_start: datetime,
    target_make: Optional[str] = None,
    scanned_makes: Optional[Sequence[str]] = None,
) -> list[tuple[int, str]]:
    """Active vehicles whose last_seen_at is older than this session's start.

    These are cards that did NOT appear in the current listing scan — either
    they've been delisted (sold), or turbo.az's search index had a transient
    hiccup. Side effect: every returned row gets `needs_detail_refresh=TRUE`
    so the next Details Update run will fetch its detail page and either
    confirm delisted (mark_delisted) or refresh data (update_vehicle_detail).

    Returns: [(vehicle_id, url), ...] ordered by id for deterministic runs.

    Scope guards (apply in priority order, first match wins):
      * `target_make` set → restrict to that make only. Make-scope runs always
        know exactly what was scanned.
      * `scanned_makes` set → restrict to those makes (case-insensitive).
        Used by --listing-full runs to avoid false-deactivating un-scanned
        makes when the run was CF-blocked partway through. Empty list →
        return [] immediately (degenerate run, nothing was scanned cleanly).
      * Neither set → operate globally (legacy Celery flow). Emit a warning
        so future regressions are visible — every modern caller should pass
        a scope hint.
    """
    if scanned_makes is not None and not target_make and len(scanned_makes) == 0:
        log.info("select_delist_suspects: scanned_makes is empty — skipping")
        return []

    sql = (
        "UPDATE vehicles "
        "   SET needs_detail_refresh = TRUE "
        " WHERE status = 'active' AND last_seen_at < %s"
    )
    params: list = [session_start]
    if target_make:
        sql += " AND LOWER(make) = LOWER(%s)"
        params.append(target_make)
    elif scanned_makes is not None:
        sql += " AND LOWER(make) = ANY(%s)"
        params.append([m.lower() for m in scanned_makes])
    else:
        log.warning(
            "select_delist_suspects called without scope guard — "
            "operating globally. A partial listing run may now mass-flag "
            "un-scanned makes as delist suspects."
        )
    sql += " RETURNING id, url"

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    conn.commit()
    return sorted([(r["id"], r["url"]) for r in rows], key=lambda x: x[0])
