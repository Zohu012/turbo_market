"""
Lifecycle check — bulk-deactivates vehicles no longer live on turbo.az.

After a listing scan collects all live turbo_ids, this module compares against
the DB and marks any missing active vehicles as 'inactive'. It also freezes
days_to_sell at the point of deactivation, carrying over any prior active
windows via active_days_accumulated so reactivated listings don't lose time.

Uses psycopg2 (sync) to stay consistent with the rest of the Celery pipeline
and avoid asyncio.run() conflicts inside Celery chord callbacks.
"""
import logging
from collections import Counter
from datetime import datetime, timezone

from psycopg2.extensions import connection as PGConnection

log = logging.getLogger(__name__)


def run_lifecycle_check_sync(conn: PGConnection, live_ids: set[int]) -> int:
    """
    Mark active vehicles not in live_ids as inactive.
    Returns count of deactivated vehicles.
    """
    if not live_ids:
        log.warning("lifecycle_check: live_ids is empty — skipping to avoid mass deactivation")
        return 0

    now = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        cur.execute(
            "CREATE TEMP TABLE _live_ids (turbo_id INTEGER PRIMARY KEY) ON COMMIT DROP"
        )

        # Bulk insert in chunks to avoid parameter limits
        ids_list = list(live_ids)
        for i in range(0, len(ids_list), 10_000):
            chunk = ids_list[i : i + 10_000]
            values = ", ".join(f"({tid})" for tid in chunk)
            cur.execute(
                f"INSERT INTO _live_ids (turbo_id) VALUES {values} ON CONFLICT DO NOTHING"
            )

        # Freeze days_to_sell on deactivation:
        #   days_to_sell = active_days_accumulated +
        #                  GREATEST(0, EXTRACT(DAY FROM now - COALESCE(last_activated_at, date_added)))
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
               AND NOT EXISTS (
                   SELECT 1 FROM _live_ids l WHERE l.turbo_id = vehicles.turbo_id
               )
            RETURNING id, seller_id
            """,
            (now, now, now),
        )
        deactivated = cur.fetchall()

    count = len(deactivated)

    if count > 0:
        seller_ids = [row[1] for row in deactivated if row[1]]
        if seller_ids:
            with conn.cursor() as cur:
                for sid, sold_count in Counter(seller_ids).items():
                    cur.execute(
                        "UPDATE sellers SET total_sold = total_sold + %s WHERE id = %s",
                        (sold_count, sid),
                    )

    conn.commit()
    log.info(f"Lifecycle check: deactivated {count} vehicles")
    return count
