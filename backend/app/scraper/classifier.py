"""
Sweep-end delist classifier for the staged listing → details flow.

Listing pass (run_local.py / parallel.py):
  1. Open or join a Sweep (one logical pass over all queued makes — see
     app.scraper.sweep). Every sighted card gets stamped with the current
     sweep's id via upsert_listing.
  2. After every queued make hits `done` AND the run was not user-stopped
     (sweep is "complete"), call select_delist_suspects to flag every active
     row in the scanned makes whose last_seen_sweep_id != current_sweep_id.
     Side effect: those rows get needs_detail_refresh=TRUE.

Details Update (run_local.py --details-update / parallel mode='update') drains
the needs_detail_refresh=TRUE queue. The detail page is the single authority
on "alive on turbo.az": healthy → stays active and clears the flag; delisted
marker → mark_delisted flips status to inactive.

There is no longer a missing_scan_count two-miss rule — the staged flow
relies on the detail run for confirmation rather than a counter heuristic.
The legacy run_lifecycle_check_sync wrapper in lifecycle.py is kept only for
the Celery scrape task chord callback.
"""
import logging
from typing import Sequence

import psycopg2.extras
from psycopg2.extensions import connection as PGConnection

log = logging.getLogger(__name__)


def select_delist_suspects(
    conn: PGConnection,
    sweep_id: int,
    scanned_makes: Sequence[str],
) -> list[tuple[int, str]]:
    """Active vehicles in `scanned_makes` whose last_seen_sweep_id is stale.

    Side effect: every returned row gets `needs_detail_refresh=TRUE` so the
    next Details Update will fetch its detail page and either confirm
    delisted (mark_delisted) or refresh data (update_vehicle_detail).

    Scope guard: `scanned_makes` lists every make that finished cleanly in
    the current sweep. Empty list → return []; we never run this query
    globally because a partial sweep would mass-flag rows in un-scanned
    makes. Callers must only invoke this once a sweep is complete.

    Returns: [(vehicle_id, url), ...] ordered by id.
    """
    if not scanned_makes:
        log.info("select_delist_suspects: scanned_makes is empty — skipping")
        return []

    sql = (
        "UPDATE vehicles "
        "   SET needs_detail_refresh = TRUE "
        " WHERE status = 'active' "
        "   AND LOWER(make) = ANY(%s) "
        "   AND (last_seen_sweep_id IS NULL OR last_seen_sweep_id <> %s) "
        " RETURNING id, url"
    )
    params = ([m.lower() for m in scanned_makes], sweep_id)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    conn.commit()
    return sorted([(r["id"], r["url"]) for r in rows], key=lambda x: x[0])
