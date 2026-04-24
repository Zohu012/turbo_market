#!/usr/bin/env python3
"""
Standalone local scraper — staged daily-refresh flow for turbo.az → managed Postgres.

Run from the backend/ directory:
    python scripts/run_local.py                  # full scan
    python scripts/run_local.py --make Toyota    # single-make partial scan
    python scripts/run_local.py --headless       # headless mode (for cron)
    python scripts/run_local.py --fresh          # ignore checkpoint, start from first make
    python scripts/run_local.py --details-only   # skip Phase 1, only fetch missing details
    python scripts/run_local.py --skip-details   # only Phase 1 (listings), no detail pages
    python scripts/run_local.py --skip-lifecycle # no sold/removed deactivation

Staged flow (full scan):
  Phase 1  Listing scan. upsert_listing stamps every sighted card with
           last_seen_at = session_start; returns needs_detail=True for new +
           bumped rows (new + reactivated + date_updated_turbo drift). Those
           IDs are collected inline for Phase 3.

  Phase 2  Classification (SQL-only). select_delist_suspects finds active
           vehicles whose last_seen_at < session_start — i.e. cards that did
           NOT appear in this session's scan. Zero detail hits.

  Phase 3  Unified detail fetch. Single loop over new ∪ bumped ∪ suspects.
           For each: scrape_detail → dispatch on detail["delisted"]:
             delisted     → mark_delisted + persist_view_count (day-1 deactivation)
             not delisted → update_vehicle_detail
                            (if it was a suspect, remember for Phase 4)

  Phase 4  Safety sweep. Any suspect that came back not-delisted-but-absent
           gets missing_scan_count bumped. Bulk deactivate rows at >= 2 misses
           (two-miss guard against transient paginator hiccups).

Checkpoint/resume:
    Phase 1 saves last completed make to scraper_checkpoint.txt; next run skips
    done makes. Cleared when Phase 1 finishes cleanly. --fresh ignores it.
    Phase 2-4 are pure DB state — no file-based checkpoint needed.

Set environment via backend/.env:
    SYNC_DATABASE_URL=postgresql://turbo:PASS@host.db.ondigitalocean.com:25060/turbo_market?sslmode=require
    SCRAPER_MODE=cdp         # cdp (default, needs Chrome open) | headless
    CDP_URL=http://localhost:9222
    DELAY_SECONDS=1.5
    AZN_PER_USD=1.7
"""
import argparse
import logging
import os
import sys
from pathlib import Path

# Allow running from backend/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scraper_local.log"),
    ],
)
log = logging.getLogger(__name__)

from app.scraper.browser import BrowserManager
from app.scraper.listing_scraper import get_all_makes, scrape_make_pages
from app.scraper.detail_scraper import scrape_detail
from app.scraper.pipeline import (
    get_sync_conn,
    upsert_listing,
    update_vehicle_detail,
    mark_delisted,
    persist_view_count,
)
from app.scraper.session import create_session, finish_session, update_session
from app.scraper.classifier import select_delist_suspects
from app.scraper.lifecycle import (
    increment_misses_for_ids,
    run_safety_deactivate,
)


CHECKPOINT_FILE = Path(__file__).parent.parent / "scraper_checkpoint.txt"


def _read_checkpoint_lines() -> dict[str, str]:
    """Parse checkpoint file into a key→value dict.

    Phase-1 line format:  ``make_name`` or ``make_name:page``  (key = "phase1")
    Detail line format:   ``detail:vehicle_id``               (key = "detail")
    """
    result: dict[str, str] = {}
    if not CHECKPOINT_FILE.exists():
        return result
    for raw in CHECKPOINT_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("detail:"):
            result["detail"] = line[7:]
        else:
            result["phase1"] = line
    return result


def _write_checkpoint_lines(lines: dict[str, str]) -> None:
    parts = []
    if "phase1" in lines:
        parts.append(lines["phase1"])
    if "detail" in lines:
        parts.append(f"detail:{lines['detail']}")
    if parts:
        CHECKPOINT_FILE.write_text("\n".join(parts), encoding="utf-8")
    elif CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()


def load_checkpoint() -> tuple[str | None, int]:
    """Load Phase-1 checkpoint. Returns (make_name, start_page) or (None, 1)."""
    data = _read_checkpoint_lines()
    val = data.get("phase1", "")
    if val:
        idx = val.rfind(":")
        if idx > 0 and val[idx + 1:].isdigit():
            return val[:idx], int(val[idx + 1:])
        return val, 1
    return None, 1


def save_checkpoint(make_name: str, page_num: int = None) -> None:
    data = _read_checkpoint_lines()
    data["phase1"] = f"{make_name}:{page_num}" if page_num else make_name
    _write_checkpoint_lines(data)


def clear_checkpoint() -> None:
    """Clear Phase-1 checkpoint (preserves detail checkpoint if present)."""
    data = _read_checkpoint_lines()
    data.pop("phase1", None)
    _write_checkpoint_lines(data)


def load_detail_checkpoint() -> int | None:
    """Return last successfully processed vehicle_id from a previous details run."""
    val = _read_checkpoint_lines().get("detail", "")
    return int(val) if val.isdigit() else None


def save_detail_checkpoint(vehicle_id: int) -> None:
    data = _read_checkpoint_lines()
    data["detail"] = str(vehicle_id)
    _write_checkpoint_lines(data)


def clear_detail_checkpoint() -> None:
    """Clear detail checkpoint (preserves Phase-1 checkpoint if present)."""
    data = _read_checkpoint_lines()
    data.pop("detail", None)
    _write_checkpoint_lines(data)


def fetch_pending_details(conn, target_make: str = None) -> list[tuple[int, str]]:
    """Vehicles that still need a detail-page fetch — active rows with no
    raw_detail_json yet. Used by --details-only and as a safety backstop so
    a crashed Phase 3 can be resumed on the next run.
    """
    sql = (
        "SELECT id, url FROM vehicles "
        "WHERE status = 'active' AND raw_detail_json IS NULL"
    )
    params: tuple = ()
    if target_make:
        sql += " AND LOWER(make) = LOWER(%s)"
        params = (target_make,)
    sql += " ORDER BY id"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [(row[0], row[1]) for row in cur.fetchall()]


def run(
    target_make: str = None,
    fresh: bool = False,
    details_only: bool = False,
    skip_details: bool = False,
    skip_lifecycle: bool = False,
):
    log.info("=== turbo_market local scraper starting ===")
    browser = BrowserManager()
    browser.start()
    conn = get_sync_conn()

    # ── Open session up-front so we have a canonical session_start to stamp
    # on every sighted card AND use as the Phase 2 classification threshold. ─
    session_id, session_start = create_session(
        conn,
        job_type="full_scan" if not target_make else "make_scan",
        triggered_by="local",
        target_make=target_make,
    )
    log.info(f"Session {session_id} started at {session_start.isoformat()}")

    counters = {"found": 0, "new": 0, "updated": 0, "deactivated": 0}
    session_status = "running"
    session_error: str | None = None

    try:
        page = browser.get_page()
        # (vehicle_id, url) for rows needing detail — new + bumped + reactivated.
        needs_detail_ids: list[tuple[int, str]] = []

        # ── Phase 1: listing scan ────────────────────────────────────────────
        if not details_only:
            all_makes = get_all_makes(page)

            if target_make:
                makes = [
                    m for m in all_makes if m["name"].lower() == target_make.lower()
                ]
                if not makes:
                    log.error(
                        f"Make '{target_make}' not found. "
                        f"Available (first 10): {[m['name'] for m in all_makes[:10]]}..."
                    )
                    session_status = "failed"
                    session_error = f"Make '{target_make}' not found"
                    return
                resume_from_page = 1
            else:
                makes = all_makes
                resume_from_page = 1
                if fresh:
                    clear_checkpoint()
                else:
                    last_make, resume_from_page = load_checkpoint()
                    if last_make:
                        idx = next(
                            (i for i, m in enumerate(makes) if m["name"] == last_make),
                            -1,
                        )
                        if idx >= 0:
                            if resume_from_page > 1:
                                # Make was interrupted mid-scrape — include it, start from saved page.
                                makes = makes[idx:]
                                log.info(
                                    f"Resuming '{last_make}' from page {resume_from_page} — "
                                    f"skipping {idx} already-done makes, {len(makes)} remaining"
                                )
                            else:
                                # Make completed cleanly — skip it entirely.
                                makes = makes[idx + 1:]
                                log.info(
                                    f"Resuming after completed make '{last_make}' — "
                                    f"skipping {idx + 1} already-done, {len(makes)} remaining"
                                )
                        else:
                            log.warning(
                                f"Checkpoint make '{last_make}' not in current list — ignoring"
                            )
                            resume_from_page = 1

            log.info(f"Phase 1: scanning {len(makes)} make(s)")

            for make in makes:
                log.info(f"[make] {make['name']}")
                committed = {"n": 0}
                current_page = {"num": resume_from_page}

                def _commit_page(vehicles_on_page, page_num):
                    # Per-page commit — preserves earlier pages if a later
                    # page times out. upsert_listing also records per-row
                    # needs_detail via its return value.
                    for v in vehicles_on_page:
                        vid, action, _, needs_detail = upsert_listing(
                            conn, v, session_start=session_start
                        )
                        counters["found"] += 1
                        if action == "new":
                            counters["new"] += 1
                        elif action == "updated":
                            counters["updated"] += 1
                        if needs_detail:
                            needs_detail_ids.append((vid, v["url"]))
                    committed["n"] += len(vehicles_on_page)
                    current_page["num"] = page_num
                    if not target_make:
                        save_checkpoint(make["name"], page_num)

                try:
                    vehicles = scrape_make_pages(
                        page, make, start_page=resume_from_page, on_page_complete=_commit_page
                    )
                    log.info(
                        f"  {make['name']}: {len(vehicles)} found, "
                        f"{committed['n']} committed"
                    )
                except Exception as e:
                    log.error(
                        f"  {make['name']} failed after page {current_page['num']}, "
                        f"committed {committed['n']} vehicles: {e}"
                    )
                    continue
                finally:
                    if not target_make:
                        save_checkpoint(make["name"])
                    resume_from_page = 1

            if not target_make:
                clear_checkpoint()

            # Persist counters mid-session so a crash between here and
            # finish_session() still leaves something in scrape_jobs.
            update_session(
                conn,
                session_id,
                listings_found=counters["found"],
                listings_new=counters["new"],
                listings_updated=counters["updated"],
            )
        else:
            log.info("Phase 1 skipped (--details-only)")

        do_lifecycle = (
            not target_make and not details_only and not skip_lifecycle
        )

        # ── Phase 2: classification (SQL-only, zero detail hits) ─────────────
        # Rows that are still active but were absent from this session's
        # listing scan. Scope-safe via target_make.
        if details_only or skip_details:
            # No Phase 1 in these modes → no meaningful suspects to compute.
            delist_suspects: list[tuple[int, str]] = []
        else:
            delist_suspects = select_delist_suspects(
                conn, session_start, target_make
            )
            log.info(
                f"Phase 2: {len(delist_suspects)} delist-suspect(s) "
                f"(active rows absent from this scan)"
            )

        # ── Detail browser tab — reused across Phase 3 ───────────────────────
        # One persistent tab preserves the Cloudflare session: one solved
        # challenge covers every subsequent navigation in this run.
        need_detail_tab = (not skip_details) or (
            do_lifecycle and len(delist_suspects) > 0
        )
        detail_page = browser.new_page() if need_detail_tab else None

        suspect_ids = {vid for vid, _ in delist_suspects}
        still_absent_not_delisted: list[int] = []

        try:
            # ── Phase 3: unified detail fetch ────────────────────────────────
            # Union new ∪ bumped ∪ delist-suspects (de-duped by vehicle id —
            # a vehicle could in theory appear in both if it was bumped AND
            # then went absent, but dedup is harmless).
            to_fetch: dict[int, str] = {}
            if not skip_details:
                for vid, url in needs_detail_ids:
                    to_fetch[vid] = url
            if do_lifecycle:
                for vid, url in delist_suspects:
                    to_fetch.setdefault(vid, url)

            # --details-only backstop: pick up any active row missing raw_detail_json
            # (e.g. a previous crashed Phase 3).
            if details_only or (not skip_details and not to_fetch):
                for vid, url in fetch_pending_details(conn, target_make):
                    to_fetch.setdefault(vid, url)

            # ── Detail checkpoint resume (--details-only only) ───────────────
            # fetch_pending_details is sorted by id, so filtering by
            # last_detail_id gives a clean resume point. Not applied for full
            # scans where to_fetch ordering is not strictly by id.
            if details_only:
                last_detail_id = load_detail_checkpoint()
                if last_detail_id is not None:
                    before = len(to_fetch)
                    to_fetch = {vid: url for vid, url in to_fetch.items() if vid > last_detail_id}
                    skipped = before - len(to_fetch)
                    if skipped:
                        log.info(
                            f"Phase 3: resuming from detail checkpoint "
                            f"(last id={last_detail_id}, skipping {skipped} already-done)"
                        )
            else:
                last_detail_id = None

            if skip_details:
                log.info("Phase 3 skipped (--skip-details)")
            elif not to_fetch:
                log.info("Phase 3: nothing to fetch (no new/bumped/suspect rows)")
            else:
                log.info(
                    f"Phase 3: fetching details for {len(to_fetch)} "
                    f"vehicle(s) ({len(needs_detail_ids)} new/bumped, "
                    f"{len(suspect_ids)} suspect, union of both)"
                )

                total = len(to_fetch)
                for i, (vehicle_id, url) in enumerate(to_fetch.items(), 1):
                    if i % 50 == 0 or i == total:
                        log.info(f"  Details: {i}/{total}")
                    try:
                        detail = scrape_detail(detail_page, url)
                    except Exception as e:
                        log.warning(f"  Detail fetch failed for {url}: {e}")
                        continue

                    if not detail:
                        continue

                    if detail.get("delisted"):
                        # Delisted → finalise + capture final VC in one shot.
                        try:
                            mark_delisted(conn, vehicle_id)
                            scraped_vc = detail.get("view_count_scraped")
                            if scraped_vc is not None:
                                persist_view_count(conn, vehicle_id, scraped_vc)
                        except Exception as e:
                            log.warning(
                                f"  delisted handling failed for vehicle "
                                f"{vehicle_id}: {e}"
                            )
                    else:
                        # Live listing — full detail update (specs, VC, M2M, …).
                        try:
                            update_vehicle_detail(conn, vehicle_id, detail)
                        except Exception as e:
                            log.warning(
                                f"  update_vehicle_detail failed for vehicle "
                                f"{vehicle_id}: {e}"
                            )
                            continue
                        # Suspect came back not-delisted → could be paginator
                        # lag; defer to Phase 4's two-miss guard.
                        if vehicle_id in suspect_ids:
                            still_absent_not_delisted.append(vehicle_id)

                    # Persist detail progress after every successful vehicle so
                    # a crash can resume from this point on the next run.
                    if details_only:
                        save_detail_checkpoint(vehicle_id)

                if details_only:
                    clear_detail_checkpoint()

            # ── Phase 4: safety sweep (two-miss deactivation) ────────────────
            if not do_lifecycle:
                if skip_lifecycle:
                    log.info("Phase 4 skipped (--skip-lifecycle)")
            else:
                bumped = increment_misses_for_ids(conn, still_absent_not_delisted)
                if bumped:
                    log.info(
                        f"Phase 4: bumped missing_scan_count for {bumped} "
                        f"suspect(s) that weren't delisted"
                    )
                deactivated = run_safety_deactivate(conn)
                counters["deactivated"] = deactivated
                log.info(
                    f"Phase 4: deactivated {deactivated} vehicle(s) "
                    f"(>= 2 consecutive misses)"
                )
        finally:
            if detail_page is not None:
                browser.close_page(detail_page)

        session_status = "done"
        log.info("=== Scan complete ===")

    except Exception as e:
        session_status = "failed"
        session_error = f"{type(e).__name__}: {e}"
        log.exception("Scan failed with unhandled exception")
        raise
    finally:
        try:
            finish_session(
                conn,
                session_id,
                status=session_status,
                error_message=session_error,
                listings_found=counters["found"],
                listings_new=counters["new"],
                listings_updated=counters["updated"],
                listings_deactivated=counters["deactivated"],
            )
        except Exception as e:
            log.warning(f"finish_session failed: {e}")
        conn.close()
        browser.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="turbo_market local scraper")
    parser.add_argument("--make", help="Scrape only this make (e.g. Toyota)")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Force headless mode — overrides SCRAPER_MODE in .env (use for cron)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore checkpoint and start from the first make",
    )
    parser.add_argument(
        "--details-only",
        action="store_true",
        help="Skip Phase 1 (listings) — only fetch missing detail pages",
    )
    parser.add_argument(
        "--skip-details",
        action="store_true",
        help="Skip Phase 3 (detail pages) — listings only",
    )
    parser.add_argument(
        "--skip-lifecycle",
        action="store_true",
        help="Skip Phase 4 (sold/removed deactivation)",
    )
    args = parser.parse_args()

    if args.headless:
        os.environ["SCRAPER_MODE"] = "headless"

    run(
        target_make=args.make,
        fresh=args.fresh,
        details_only=args.details_only,
        skip_details=args.skip_details,
        skip_lifecycle=args.skip_lifecycle,
    )
