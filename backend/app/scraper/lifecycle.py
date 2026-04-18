"""
Lifecycle check — bulk-deactivates vehicles no longer live on turbo.az.

After a listing scan collects all live turbo_ids, this module compares against
the DB and marks any missing active vehicles as 'inactive'.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


async def run_lifecycle_check(db: AsyncSession, live_ids: set[int]) -> int:
    """
    Mark active vehicles not in live_ids as inactive.
    Returns count of deactivated vehicles.
    """
    if not live_ids:
        log.warning("lifecycle_check: live_ids is empty — skipping to avoid mass deactivation")
        return 0

    now = datetime.now(timezone.utc)

    # Create temp table and bulk insert live IDs
    await db.execute(text("CREATE TEMP TABLE _live_ids (turbo_id INTEGER PRIMARY KEY) ON COMMIT DROP"))
    # Insert in chunks to avoid parameter limits
    chunk_size = 10_000
    ids_list = list(live_ids)
    for i in range(0, len(ids_list), chunk_size):
        chunk = ids_list[i:i + chunk_size]
        values = ", ".join(f"({tid})" for tid in chunk)
        await db.execute(text(f"INSERT INTO _live_ids (turbo_id) VALUES {values} ON CONFLICT DO NOTHING"))

    result = await db.execute(
        text("""
            UPDATE vehicles
            SET status = 'inactive',
                date_deactivated = :now,
                date_updated = :now
            WHERE status = 'active'
              AND NOT EXISTS (
                  SELECT 1 FROM _live_ids l WHERE l.turbo_id = vehicles.turbo_id
              )
            RETURNING id, turbo_id, seller_id
        """),
        {"now": now},
    )
    deactivated = result.fetchall()
    count = len(deactivated)

    if count > 0:
        # Update seller total_sold counters
        seller_ids = [row.seller_id for row in deactivated if row.seller_id]
        if seller_ids:
            from sqlalchemy import func
            for sid in set(seller_ids):
                sold_count = seller_ids.count(sid)
                await db.execute(
                    text("UPDATE sellers SET total_sold = total_sold + :n WHERE id = :sid"),
                    {"n": sold_count, "sid": sid},
                )

    await db.commit()
    log.info(f"Lifecycle check: deactivated {count} vehicles")
    return count
