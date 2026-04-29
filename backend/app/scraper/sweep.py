"""Sweep lifecycle helpers for the staged Listing → Details flow.

A Sweep is one logical pass over all queued makes. It can span many sessions
(CF blocks, Ctrl-C, connection drops). Phase 2 delist classification only
fires when the sweep is complete — every queued make has hit `done` status
in the per-make sidecar AND the run was not user-stopped. This kills the
multi-session false-positive trap that the per-session `last_seen_at`
predicate used to fall into.

A Session is one process invocation. Each Session attaches to either:
  * the Sweep currently `running` for this `(job_type, target_make)` scope, or
  * a fresh Sweep, if no running sweep exists for that scope.

The "no running sweep exists" signal lines up naturally with sidecar
emptiness — the sidecar is wiped at sweep completion, so a fresh sweep is
exactly what the next Session sees when it starts on an empty sidecar.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

import psycopg2.extras
from psycopg2.extensions import connection as PGConnection

log = logging.getLogger(__name__)


@dataclass
class Sweep:
    id: int
    job_type: str
    target_make: Optional[str]
    started_at: datetime
    makes_total: Optional[int]


def get_or_create_sweep(
    conn: PGConnection,
    job_type: str,
    target_make: Optional[str],
    makes_total: Optional[int],
) -> Sweep:
    """Return the running sweep for this scope, or open a fresh one.

    Scope is `(job_type, target_make)` — `--listing-full` and `--listing-make`
    have separate sweep lifecycles, and a per-make sweep does not share state
    with a full-catalogue sweep. `target_make` is normalized to its canonical
    case so resume comparisons stay stable.
    """
    started_at = datetime.now(timezone.utc)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, job_type, target_make, started_at, makes_total
              FROM scrape_sweeps
             WHERE status = 'running'
               AND job_type = %s
               AND COALESCE(LOWER(target_make), '') = COALESCE(LOWER(%s), '')
             ORDER BY started_at DESC
             LIMIT 1
            """,
            (job_type, target_make),
        )
        row = cur.fetchone()
        if row is not None:
            sweep = Sweep(
                id=row["id"],
                job_type=row["job_type"],
                target_make=row["target_make"],
                started_at=row["started_at"],
                makes_total=row["makes_total"],
            )
            # If the caller now knows a different total (e.g. resume picked a
            # different queue), keep the most recent count.
            if makes_total is not None and makes_total != sweep.makes_total:
                cur.execute(
                    "UPDATE scrape_sweeps SET makes_total = %s WHERE id = %s",
                    (makes_total, sweep.id),
                )
                conn.commit()
                sweep.makes_total = makes_total
            log.info(
                f"Joining existing sweep {sweep.id} "
                f"(started_at={sweep.started_at.isoformat()}, "
                f"makes_total={sweep.makes_total})"
            )
            return sweep

        cur.execute(
            """
            INSERT INTO scrape_sweeps
                (job_type, target_make, started_at, status, makes_total)
            VALUES (%s, %s, %s, 'running', %s)
            RETURNING id, job_type, target_make, started_at, makes_total
            """,
            (job_type, target_make, started_at, makes_total),
        )
        row = cur.fetchone()
    conn.commit()
    sweep = Sweep(
        id=row["id"],
        job_type=row["job_type"],
        target_make=row["target_make"],
        started_at=row["started_at"],
        makes_total=row["makes_total"],
    )
    log.info(
        f"Opened sweep {sweep.id} "
        f"(job_type={job_type}, target_make={target_make}, "
        f"makes_total={makes_total})"
    )
    return sweep


def update_sweep_progress(
    conn: PGConnection, sweep_id: int, makes_done: int
) -> None:
    """Patch makes_done. Cheap, called once per Phase-2 trigger evaluation."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scrape_sweeps SET makes_done = %s WHERE id = %s",
            (makes_done, sweep_id),
        )
    conn.commit()


def complete_sweep(
    conn: PGConnection, sweep_id: int, scanned_makes: Iterable[str]
) -> None:
    """Mark the sweep terminal — Phase 2 has run, sidecar will be wiped."""
    now = datetime.now(timezone.utc)
    makes_list = list(scanned_makes)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE scrape_sweeps
               SET status        = 'completed',
                   finished_at   = %s,
                   makes_done    = %s,
                   scanned_makes = %s::jsonb
             WHERE id = %s
            """,
            (now, len(makes_list), psycopg2.extras.Json(makes_list), sweep_id),
        )
    conn.commit()
    log.info(
        f"Sweep {sweep_id} completed at {now.isoformat()} "
        f"({len(makes_list)} make(s) scanned)"
    )


def add_scanned_make(conn: PGConnection, sweep_id: int, make_name: str) -> int:
    """Append a make to sweep.scanned_makes (set-semantics, lowercase).

    Used by the serial listing path which doesn't maintain a per-make sidecar
    — the sweep row itself accumulates the set across sessions. Returns the
    new length of scanned_makes.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE scrape_sweeps
               SET scanned_makes = COALESCE(scanned_makes, '[]'::jsonb)
                 || (
                   CASE
                     WHEN scanned_makes ? %s THEN '[]'::jsonb
                     ELSE to_jsonb(ARRAY[%s])
                   END
                 ),
                   makes_done = jsonb_array_length(
                     COALESCE(scanned_makes, '[]'::jsonb)
                       || (
                         CASE
                           WHEN scanned_makes ? %s THEN '[]'::jsonb
                           ELSE to_jsonb(ARRAY[%s])
                         END
                       )
                   )
             WHERE id = %s
            RETURNING makes_done
            """,
            (
                make_name.lower(), make_name.lower(),
                make_name.lower(), make_name.lower(),
                sweep_id,
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return int(row[0]) if row else 0


def get_scanned_makes(conn: PGConnection, sweep_id: int) -> list[str]:
    """Read the persisted scanned_makes JSONB list off the sweep row."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT scanned_makes FROM scrape_sweeps WHERE id = %s",
            (sweep_id,),
        )
        row = cur.fetchone()
    if not row or row[0] is None:
        return []
    return list(row[0])


def is_sweep_complete(
    sidecar_progress: dict, makes_total: Optional[int]
) -> bool:
    """Sweep complete iff every queued make hit `done` in the sidecar.

    `sidecar_progress` shape: `{name: (status, next_page)}` — the dict
    returned by `read_make_progress`. `makes_total` is the count the sweep
    was opened with; we compare against it so a stop-then-resume mid-sweep
    where the sidecar still records in_flight rows correctly returns False.
    """
    if not sidecar_progress:
        return False
    done_count = sum(1 for st, _ in sidecar_progress.values() if st == "done")
    if makes_total is not None:
        return done_count >= makes_total
    return all(st == "done" for st, _ in sidecar_progress.values())
