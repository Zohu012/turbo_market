"""
Lifecycle helpers — Celery-path two-miss sold detection + bulk deactivation.

The staged Listing → Details flow (run_local.py + parallel.py) no longer uses
this module. It now relies on Sweep-based delist classification at sweep end
(see app.scraper.sweep + app.scraper.classifier) plus detail-page confirmation
via mark_delisted in pipeline.py — the detail page is the single authority on
"alive on turbo.az."

These helpers are kept for the legacy Celery chord path
(tasks.py::lifecycle_check_task) which still does "increment everything not
in live_ids, then deactivate" because it doesn't carry a session_start /
last_seen_sweep_id. Once Celery is retired, this whole module can go.

Reset of the legacy `missing_scan_count` still happens in upsert_listing()
whenever a card reappears (the column has not yet been dropped).
"""
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Optional, Sequence

import psycopg2.extras
from psycopg2.extensions import connection as PGConnection

from app.scraper.detail_scraper import scrape_detail
from app.scraper.pipeline import mark_delisted, persist_view_count

log = logging.getLogger(__name__)


# ── Building-block helpers (used by the staged flow in run_local.py) ──────────

def increment_misses_for_ids(
    conn: PGConnection, vehicle_ids: Sequence[int]
) -> int:
    """Bump `missing_scan_count` by 1 for the given active vehicle IDs.

    Callers should pass only vehicles that were *suspect* in this session and
    *failed* the delisted confirmation (i.e. detail page was reachable and
    didn't show the delisted marker). Idempotent per session: the caller is
    expected to call this once per session for the relevant ids.
    """
    if not vehicle_ids:
        return 0
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE vehicles
               SET missing_scan_count = missing_scan_count + 1,
                   date_updated = %s
             WHERE id = ANY(%s)
               AND status = 'active'
            """,
            (now, list(vehicle_ids)),
        )
        affected = cur.rowcount
    conn.commit()
    return affected


def run_safety_deactivate(conn: PGConnection) -> int:
    """Bulk-deactivate every active row with `missing_scan_count >= 2`.

    Freezes `days_to_sell = active_days_accumulated + (now - anchor)`, where
    anchor = last_activated_at OR date_added. Also bumps seller.total_sold
    for each affected seller.

    Returns number of rows deactivated.
    """
    now = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE vehicles
               SET status = 'inactive',
                   date_deactivated = %s,
                   date_updated = %s,
                   days_to_sell = COALESCE(active_days_accumulated, 0) + GREATEST(
                       0,
                       EXTRACT(DAY FROM %s - COALESCE(last_activated_at, date_added))::INTEGER
                   )
             WHERE status = 'active'
               AND missing_scan_count >= 2
            RETURNING id, seller_id
            """,
            (now, now, now),
        )
        deactivated = cur.fetchall()

    if deactivated:
        seller_ids = [row[1] for row in deactivated if row[1]]
        if seller_ids:
            with conn.cursor() as cur:
                for sid, sold_count in Counter(seller_ids).items():
                    cur.execute(
                        "UPDATE sellers SET total_sold = total_sold + %s WHERE id = %s",
                        (sold_count, sid),
                    )

    conn.commit()
    return len(deactivated)


def increment_misses_absent_from_live(
    conn: PGConnection, live_ids: set[int]
) -> None:
    """Classic flow: bump missing_scan_count for every active row whose
    turbo_id is NOT in `live_ids`.

    Used by the Celery path (it collects live_ids from a chord of per-make
    tasks and doesn't carry a session_start / last_seen_at stamp).
    """
    if not live_ids:
        return
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TEMP TABLE _live_ids (turbo_id INTEGER PRIMARY KEY) ON COMMIT DROP"
        )
        ids_list = list(live_ids)
        for i in range(0, len(ids_list), 10_000):
            chunk = ids_list[i : i + 10_000]
            values = ", ".join(f"({tid})" for tid in chunk)
            cur.execute(
                f"INSERT INTO _live_ids (turbo_id) VALUES {values} "
                f"ON CONFLICT DO NOTHING"
            )
        cur.execute(
            """
            UPDATE vehicles
               SET missing_scan_count = missing_scan_count + 1,
                   date_updated = %s
             WHERE status = 'active'
               AND NOT EXISTS (
                   SELECT 1 FROM _live_ids l WHERE l.turbo_id = vehicles.turbo_id
               )
            """,
            (now,),
        )
    conn.commit()


# ── Celery-path wrapper (legacy 3-step flow) ──────────────────────────────────

def run_lifecycle_check_sync(
    conn: PGConnection,
    live_ids: set[int],
    detail_page=None,
) -> int:
    """Legacy 3-step lifecycle for the Celery (tasks.py) path:

      1. Increment missing_scan_count for active rows absent from live_ids.
      2. If `detail_page` is provided, fetch detail once for every row at
         >= 2 misses to capture a final view-count snapshot + confirm delist.
      3. Bulk deactivate all remaining active rows at >= 2 misses.

    run_local.py no longer uses this — it composes the staged flow out of
    `increment_misses_for_ids` + `run_safety_deactivate` directly. Kept here
    so the Celery chord callback can continue to work unmodified.

    Returns the total number of newly-deactivated vehicles.
    """
    if not live_ids:
        log.warning(
            "lifecycle_check: live_ids is empty — skipping to avoid mass deactivation"
        )
        return 0

    # Step 1 — increment miss counter for active rows absent from live_ids.
    increment_misses_absent_from_live(conn, live_ids)

    # Step 2 — optional final-VC snapshot for rows at the two-miss threshold.
    delisted_ids: set[int] = set()
    if detail_page is not None:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, url FROM vehicles
                 WHERE status = 'active' AND missing_scan_count >= 2
                 ORDER BY id
                """
            )
            candidates = cur.fetchall()

        if candidates:
            log.info(
                f"Lifecycle step 2: final-VC fetch for {len(candidates)} "
                f"vehicles at two-miss threshold"
            )

        for row in candidates:
            vehicle_id = row["id"]
            url = row["url"]
            try:
                detail = scrape_detail(detail_page, url)
            except Exception as e:
                log.warning(
                    f"  Final-VC fetch failed for vehicle {vehicle_id} ({url}): {e}"
                )
                continue

            if not detail:
                continue

            scraped_vc = detail.get("view_count_scraped")
            try:
                persist_view_count(conn, vehicle_id, scraped_vc)
            except Exception as e:
                log.warning(
                    f"  Final-VC persist failed for vehicle {vehicle_id}: {e}"
                )

            if detail.get("delisted"):
                try:
                    mark_delisted(conn, vehicle_id)
                    delisted_ids.add(vehicle_id)
                except Exception as e:
                    log.warning(
                        f"  mark_delisted failed for vehicle {vehicle_id}: {e}"
                    )
            else:
                log.warning(
                    f"  Vehicle {vehicle_id} absent from index 2x but detail "
                    f"page has no delisted marker — deactivating via two-miss rule"
                )

    # Step 3 — bulk deactivate remaining active rows at >= 2 misses.
    bulk_count = run_safety_deactivate(conn)

    total = bulk_count + len(delisted_ids)
    log.info(
        f"Lifecycle check: deactivated {total} vehicles "
        f"({len(delisted_ids)} via delisted marker, {bulk_count} via two-miss threshold)"
    )
    return total
