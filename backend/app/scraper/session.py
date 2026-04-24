"""
Scrape session lifecycle helpers.

Thin wrapper around the existing `scrape_jobs` table (see
app/models/scrape_job.py) — we reuse that table instead of introducing a
parallel `scrape_sessions` table, since its shape (id, started_at, finished_at,
status, listings_*, target_make) already fits our needs.

The `started_at` returned by `create_session()` is the canonical
`session_start` — the same value must be:
  1. Written into `vehicles.last_seen_at` for every sighted card in Phase 1
     (via upsert_listing(..., session_start=...)).
  2. Passed to the classifier in Phase 2 as the threshold for delist-suspects
     (select_delist_suspects).

Using the DB-assigned clock (not the client's) keeps all of this consistent
across hosts.
"""
from datetime import datetime, timezone
from typing import Optional

import psycopg2.extras
from psycopg2.extensions import connection as PGConnection


def create_session(
    conn: PGConnection,
    job_type: str,
    triggered_by: str,
    target_make: Optional[str] = None,
    target_model: Optional[str] = None,
    celery_task_id: Optional[str] = None,
) -> tuple[int, datetime]:
    """Insert a 'running' scrape_jobs row and return (id, started_at).

    started_at is returned so callers can stamp it onto vehicles.last_seen_at
    and pass it to the classifier — all three must agree on the same instant.
    """
    started_at = datetime.now(timezone.utc)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO scrape_jobs
              (job_type, status, triggered_by, target_make, target_model,
               celery_task_id, started_at, created_at)
            VALUES
              (%s, 'running', %s, %s, %s, %s, %s, %s)
            RETURNING id, started_at
            """,
            (
                job_type,
                triggered_by,
                target_make,
                target_model,
                celery_task_id,
                started_at,
                started_at,
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return row["id"], row["started_at"]


def update_session(conn: PGConnection, session_id: int, **fields) -> None:
    """Patch any subset of scrape_jobs columns for this session."""
    if not session_id or not fields:
        return
    set_clause = ", ".join(f"{k} = %({k})s" for k in fields)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE scrape_jobs SET {set_clause} WHERE id = %(session_id)s",
            {**fields, "session_id": session_id},
        )
    conn.commit()


def finish_session(
    conn: PGConnection,
    session_id: int,
    status: str = "done",
    error_message: Optional[str] = None,
    **counters,
) -> None:
    """Mark the session terminal: set finished_at and merge any counter updates.

    `counters` accepts any of: listings_found, listings_new, listings_updated,
    listings_deactivated.
    """
    if not session_id:
        return
    fields = {
        "status": status,
        "finished_at": datetime.now(timezone.utc),
        **counters,
    }
    if error_message is not None:
        fields["error_message"] = error_message
    update_session(conn, session_id, **fields)
