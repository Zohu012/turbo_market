"""
Lifecycle check — two-miss sold detection with final view-count capture.

After a listing scan collects all live turbo_ids, this module runs three steps:

  1. SQL: increment missing_scan_count for active vehicles absent from live_ids.
  2. Python + browser: for every vehicle whose counter has reached >= 2,
     fetch the detail page once to capture a final view-count snapshot
     (turbo.az still displays the view count on delisted pages). If the
     delisted marker is present, mark_delisted() finalises the row; otherwise
     the bulk UPDATE in step 3 does.
  3. SQL: flip status to 'inactive' for all remaining active rows at >= 2,
     freezing days_to_sell.

Two-miss rule: a listing must be absent on two consecutive full scans before
deactivation. Reset happens automatically in upsert_listing() whenever the
card re-appears.

Uses psycopg2 (sync) to stay consistent with the rest of the Celery pipeline
and avoid asyncio.run() conflicts inside Celery chord callbacks.
"""
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

import psycopg2.extras
from psycopg2.extensions import connection as PGConnection

from app.scraper.detail_scraper import scrape_detail
from app.scraper.pipeline import mark_delisted, persist_view_count

log = logging.getLogger(__name__)


def run_lifecycle_check_sync(
    conn: PGConnection,
    live_ids: set[int],
    detail_page=None,
) -> int:
    """
    Mark active vehicles not in live_ids as inactive, with two-miss protection
    and a final view-count snapshot on deactivation.

    If `detail_page` is None, step 2 is skipped — deactivations still happen
    via step 3, but no final VC is captured. Callers that have a browser open
    (run_local.py, tasks.lifecycle_check_task) should pass it through.

    Returns the total number of newly-deactivated vehicles.
    """
    if not live_ids:
        log.warning(
            "lifecycle_check: live_ids is empty — skipping to avoid mass deactivation"
        )
        return 0

    now = datetime.now(timezone.utc)

    # ── Step 1: increment miss counter for active rows absent from live_ids ─
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TEMP TABLE _live_ids (turbo_id INTEGER PRIMARY KEY) ON COMMIT DROP"
        )

        ids_list = list(live_ids)
        for i in range(0, len(ids_list), 10_000):
            chunk = ids_list[i : i + 10_000]
            values = ", ".join(f"({tid})" for tid in chunk)
            cur.execute(
                f"INSERT INTO _live_ids (turbo_id) VALUES {values} ON CONFLICT DO NOTHING"
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

    # ── Step 2: final VC snapshot for rows at the two-miss threshold ────────
    # On delisted pages turbo.az still surfaces the view count, so we get a
    # genuine "last count of this active window" even after the seller closed
    # the listing. Skipped if no browser was passed.
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
                # Absent from index for 2 scans but reachable without a
                # delisted marker — likely a turbo.az search-index hiccup.
                # Proceed to step 3 anyway; the two-miss rule has fired.
                log.warning(
                    f"  Vehicle {vehicle_id} absent from index 2x but detail "
                    f"page has no delisted marker — deactivating via two-miss rule"
                )

    # ── Step 3: bulk-deactivate any remaining active rows at the threshold ─
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
        bulk_deactivated = cur.fetchall()

    bulk_count = len(bulk_deactivated)

    if bulk_count > 0:
        seller_ids = [row[1] for row in bulk_deactivated if row[1]]
        if seller_ids:
            with conn.cursor() as cur:
                for sid, sold_count in Counter(seller_ids).items():
                    cur.execute(
                        "UPDATE sellers SET total_sold = total_sold + %s WHERE id = %s",
                        (sold_count, sid),
                    )

    conn.commit()

    total = bulk_count + len(delisted_ids)
    log.info(
        f"Lifecycle check: deactivated {total} vehicles "
        f"({len(delisted_ids)} via delisted marker, {bulk_count} via two-miss threshold)"
    )
    return total
