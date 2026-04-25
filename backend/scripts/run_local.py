#!/usr/bin/env python3
"""
Standalone local scraper — listing-pass / details-pass split (5 modes).

Run from the backend/ directory. Exactly one mode flag must be passed:

    python scripts/run_local.py --listing-full        # all makes, listing pages only
    python scripts/run_local.py --listing-make BMW    # one make, listing pages only
    python scripts/run_local.py --details-full        # FIFO every row in DB
    python scripts/run_local.py --details-full --make BMW   # FIFO scoped to one make
    python scripts/run_local.py --details-update      # only rows flagged needs_detail_refresh

Common flags:
    --headless        force headless mode (overrides SCRAPER_MODE in .env)

Listing pass (`--listing-full` / `--listing-make`):
    1. Scrape listing pages → upsert_listing flags new / reactivated /
       date_updated_turbo-bumped rows with needs_detail_refresh=TRUE.
    2. select_delist_suspects flags every active row that was absent from
       this session's scan with needs_detail_refresh=TRUE.
    3. Two-miss safety: bump missing_scan_count for those suspects, bulk
       deactivate at >= 2.

Details pass (`--details-full` / `--details-update`):
    Iterates rows by `vehicle.id` ASC. Per row:
      - delisted page → mark_delisted (status='inactive', date_deactivated,
        days_to_sell, persist final view_count).
      - live page → update_vehicle_detail (preserve_collections_if_shorter
        on --details-full to keep historical images/features/labels).
      - load failure → don't advance checkpoint; retry next run.
    --details-update additionally clears needs_detail_refresh after each row.

Checkpoint file: backend/scraper_checkpoint.txt — multiline, one key per line:
    listing_full:Chevrolet:75
    listing_make:BMW:12
    details_full:11761                  # vehicle.id
    details_full_make:Chevrolet:11761   # per-make scope is separate
    details_update:5234

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
from typing import Optional

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
    clear_needs_detail_refresh,
)
from app.scraper.session import create_session, finish_session, update_session
from app.scraper.classifier import select_delist_suspects
from app.scraper.lifecycle import (
    increment_misses_for_ids,
    run_safety_deactivate,
)


CHECKPOINT_FILE = Path(__file__).parent.parent / "scraper_checkpoint.txt"

# Order keys are written back to disk in. Stable order keeps diffs readable.
_CHECKPOINT_KEYS = (
    "listing_full",
    "listing_make",
    "details_full",
    "details_full_make",
    "details_update",
)


# ── Checkpoint I/O ──────────────────────────────────────────────────────────


def _read_checkpoint() -> dict[str, str]:
    """Parse checkpoint file into a key→value dict. Each line is `key:value`."""
    result: dict[str, str] = {}
    if not CHECKPOINT_FILE.exists():
        return result
    for raw in CHECKPOINT_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        if key in _CHECKPOINT_KEYS:
            result[key] = value
    return result


def _write_checkpoint(data: dict[str, str]) -> None:
    parts = [f"{k}:{data[k]}" for k in _CHECKPOINT_KEYS if k in data and data[k]]
    if parts:
        CHECKPOINT_FILE.write_text("\n".join(parts), encoding="utf-8")
    elif CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()


def _set_checkpoint(key: str, value: str) -> None:
    data = _read_checkpoint()
    data[key] = value
    _write_checkpoint(data)


def _clear_checkpoint(key: str) -> None:
    data = _read_checkpoint()
    data.pop(key, None)
    _write_checkpoint(data)


def _load_listing_progress(key: str) -> tuple[Optional[str], int]:
    """Decode `make_name:page_num` (or just `make_name`) → (make, page)."""
    val = _read_checkpoint().get(key, "")
    if not val:
        return None, 1
    idx = val.rfind(":")
    if idx > 0 and val[idx + 1:].isdigit():
        return val[:idx], int(val[idx + 1:])
    return val, 1


def _save_listing_progress(key: str, make_name: str, page_num: Optional[int] = None) -> None:
    val = f"{make_name}:{page_num}" if page_num else make_name
    _set_checkpoint(key, val)


def _load_details_progress(key: str) -> Optional[int]:
    val = _read_checkpoint().get(key, "")
    return int(val) if val.isdigit() else None


def _save_details_progress(key: str, vehicle_id: int) -> None:
    _set_checkpoint(key, str(vehicle_id))


# ── Listing pass ────────────────────────────────────────────────────────────


def _run_listing(
    browser: "BrowserManager",
    target_make: Optional[str] = None,
) -> None:
    """All makes (target_make=None) or one make: scrape listing pages, classify
    delist-suspects, run two-miss safety deactivate.

    No detail-page hits — anything that needs a detail fetch is queued via
    needs_detail_refresh=TRUE for the next Details Update run.
    """
    ckpt_key = "listing_make" if target_make else "listing_full"
    conn = get_sync_conn()

    session_id, session_start = create_session(
        conn,
        job_type="listing_make" if target_make else "listing_full",
        triggered_by="local",
        target_make=target_make,
    )
    log.info(f"Session {session_id} started at {session_start.isoformat()}")

    counters = {"found": 0, "new": 0, "updated": 0, "deactivated": 0}
    session_status = "running"
    session_error: Optional[str] = None

    try:
        page = browser.get_page()
        BrowserManager.block_media(page)

        # ── Phase 1: listing scan ────────────────────────────────────────────
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
            last_make, saved_page = _load_listing_progress(ckpt_key)
            if last_make and last_make.lower() == target_make.lower() and saved_page > 1:
                resume_from_page = saved_page
                log.info(f"Resuming '{target_make}' from page {resume_from_page}")
        else:
            makes = all_makes
            resume_from_page = 1
            last_make, saved_page = _load_listing_progress(ckpt_key)
            if last_make:
                idx = next(
                    (i for i, m in enumerate(makes) if m["name"] == last_make),
                    -1,
                )
                if idx >= 0:
                    if saved_page > 1:
                        makes = makes[idx:]
                        resume_from_page = saved_page
                        log.info(
                            f"Resuming '{last_make}' from page {resume_from_page} — "
                            f"skipping {idx} already-done makes, {len(makes)} remaining"
                        )
                    else:
                        makes = makes[idx + 1:]
                        log.info(
                            f"Resuming after completed make '{last_make}' — "
                            f"skipping {idx + 1} already-done, {len(makes)} remaining"
                        )
                else:
                    log.warning(
                        f"Checkpoint make '{last_make}' not in current list — ignoring"
                    )

        log.info(f"Listing pass: scanning {len(makes)} make(s)")

        for make in makes:
            log.info(f"[make] {make['name']}")
            committed = {"n": 0}
            current_page = {"num": resume_from_page}

            def _commit_page(vehicles_on_page, page_num):
                # Per-page commit — preserves earlier pages if a later page
                # times out. upsert_listing handles the per-row flagging.
                for v in vehicles_on_page:
                    _vid, action, _, _needs_detail = upsert_listing(
                        conn, v, session_start=session_start
                    )
                    counters["found"] += 1
                    if action == "new":
                        counters["new"] += 1
                    elif action == "updated":
                        counters["updated"] += 1
                committed["n"] += len(vehicles_on_page)
                current_page["num"] = page_num
                _save_listing_progress(ckpt_key, make["name"], page_num)

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
                _save_listing_progress(ckpt_key, make["name"])
                resume_from_page = 1

        _clear_checkpoint(ckpt_key)

        # Persist counters mid-session so a crash between here and
        # finish_session() still leaves something in scrape_jobs.
        update_session(
            conn,
            session_id,
            listings_found=counters["found"],
            listings_new=counters["new"],
            listings_updated=counters["updated"],
        )

        # ── Phase 2: classify delist-suspects ────────────────────────────────
        # Side effect: every suspect gets needs_detail_refresh=TRUE so the
        # next Details Update will fetch its detail page and either confirm
        # delisted (mark_delisted) or simply refresh data.
        suspects = select_delist_suspects(conn, session_start, target_make)
        log.info(
            f"Phase 2: {len(suspects)} delist-suspect(s) flagged for detail refresh"
        )

        # ── Phase 3: two-miss safety deactivate ──────────────────────────────
        # Bump missing_scan_count for every suspect; bulk-deactivate at >= 2.
        # A row that's truly delisted will be mark_delisted by Details Update
        # (faster path), but two-miss is the safety net for cases where the
        # detail page is unreachable or the user skips Details Update.
        suspect_ids = [vid for vid, _ in suspects]
        if suspect_ids:
            bumped = increment_misses_for_ids(conn, suspect_ids)
            log.info(
                f"Phase 3: bumped missing_scan_count for {bumped} suspect(s)"
            )
        deactivated = run_safety_deactivate(conn)
        counters["deactivated"] = deactivated
        log.info(
            f"Phase 3: deactivated {deactivated} vehicle(s) "
            f"(>= 2 consecutive misses)"
        )

        session_status = "done"
        log.info("=== Listing pass complete ===")

    except Exception as e:
        session_status = "failed"
        session_error = f"{type(e).__name__}: {e}"
        log.exception("Listing pass failed with unhandled exception")
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


# ── Details pass ────────────────────────────────────────────────────────────


def _run_details(
    browser: "BrowserManager",
    mode: str,
    target_make: Optional[str] = None,
) -> None:
    """Details pass — three flavours:

      mode="full"            FIFO every vehicle in DB.
      mode="full" + make     FIFO every vehicle for that make.
      mode="update"          FIFO only rows where needs_detail_refresh=TRUE.

    Per-row:
      - load failure        → don't advance checkpoint; retry next run.
      - delisted marker     → mark_delisted + persist final view_count, advance.
      - live page           → update_vehicle_detail, advance.
      mode="update" also clears needs_detail_refresh after each successful row.
    """
    if mode == "update":
        ckpt_key = "details_update"
        sql = (
            "SELECT id, url FROM vehicles "
            "WHERE needs_detail_refresh = TRUE ORDER BY id ASC"
        )
        params: tuple = ()
    elif mode == "full":
        if target_make:
            ckpt_key = "details_full_make"
            sql = (
                "SELECT id, url FROM vehicles "
                "WHERE LOWER(make) = LOWER(%s) ORDER BY id ASC"
            )
            params = (target_make,)
        else:
            ckpt_key = "details_full"
            sql = "SELECT id, url FROM vehicles ORDER BY id ASC"
            params = ()
    else:
        raise ValueError(f"unknown details mode: {mode}")

    conn = get_sync_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows: list[tuple[int, str]] = [(r[0], r[1]) for r in cur.fetchall()]

        scope_label = (
            "details-update queue" if mode == "update"
            else f"make '{target_make}'" if target_make
            else "all vehicles"
        )

        if not rows:
            log.info(f"Details pass ({mode}): nothing to do for {scope_label}")
            return

        # Resume from per-mode checkpoint (vehicle.id, FIFO).
        last_id = _load_details_progress(ckpt_key)
        if last_id is not None:
            before = len(rows)
            rows = [(vid, url) for vid, url in rows if vid > last_id]
            skipped = before - len(rows)
            if skipped:
                log.info(
                    f"Resuming {ckpt_key} past id={last_id} "
                    f"(skipped {skipped} already-done)"
                )

        log.info(f"Details pass ({mode}): {len(rows)} row(s) for {scope_label}")
        detail_page = browser.new_page()
        BrowserManager.block_media(detail_page)

        processed = delisted = load_failed = 0

        try:
            total = len(rows)
            for i, (vehicle_id, url) in enumerate(rows, 1):
                if i % 50 == 0 or i == total:
                    log.info(f"  Details: {i}/{total}")

                try:
                    detail = scrape_detail(detail_page, url)
                except Exception as e:
                    log.warning(f"  Detail fetch failed for {url}: {e}")
                    load_failed += 1
                    continue

                if not detail:
                    # Page didn't load — leave checkpoint so we retry this row.
                    load_failed += 1
                    continue

                if detail.get("delisted"):
                    try:
                        mark_delisted(conn, vehicle_id)
                        scraped_vc = detail.get("view_count_scraped")
                        if scraped_vc is not None:
                            persist_view_count(conn, vehicle_id, scraped_vc)
                        delisted += 1
                    except Exception as e:
                        log.warning(
                            f"  delisted handling failed for vehicle "
                            f"{vehicle_id}: {e}"
                        )
                        continue
                    # Backfill any spec fields the delisted page still carries
                    # (hp, condition, market_for, date_updated_turbo, raw_detail_json).
                    # preserve_collections_if_shorter=True means empty lists from the
                    # delisted page never replace existing images/features/labels.
                    try:
                        update_vehicle_detail(
                            conn, vehicle_id, detail,
                            preserve_collections_if_shorter=True,
                        )
                    except Exception as e:
                        log.warning(
                            f"  delisted spec backfill failed for vehicle "
                            f"{vehicle_id}: {e}"
                        )
                else:
                    try:
                        update_vehicle_detail(
                            conn,
                            vehicle_id,
                            detail,
                            preserve_collections_if_shorter=(mode == "full"),
                        )
                        processed += 1
                    except Exception as e:
                        log.warning(
                            f"  update_vehicle_detail failed for vehicle "
                            f"{vehicle_id}: {e}"
                        )
                        continue

                # Successful processing — advance checkpoint and clear queue flag.
                _save_details_progress(ckpt_key, vehicle_id)
                if mode == "update":
                    try:
                        clear_needs_detail_refresh(conn, vehicle_id)
                    except Exception as e:
                        log.warning(
                            f"  clear_needs_detail_refresh failed for vehicle "
                            f"{vehicle_id}: {e}"
                        )
        finally:
            browser.close_page(detail_page)

        _clear_checkpoint(ckpt_key)
        log.info(
            f"Details pass ({mode}) complete — processed={processed}, "
            f"delisted={delisted}, load_failed={load_failed}"
        )
    finally:
        conn.close()


# ── Entry point ─────────────────────────────────────────────────────────────


def run(
    listing_full: bool = False,
    listing_make: Optional[str] = None,
    details_full: bool = False,
    details_update: bool = False,
    target_make: Optional[str] = None,
) -> None:
    log.info("=== turbo_market local scraper starting ===")
    browser = BrowserManager()
    browser.start()

    try:
        if listing_full:
            _run_listing(browser, target_make=None)
        elif listing_make:
            _run_listing(browser, target_make=listing_make)
        elif details_update:
            _run_details(browser, mode="update")
        elif details_full:
            _run_details(browser, mode="full", target_make=target_make)
        else:
            log.error(
                "No mode specified. Use one of: --listing-full, "
                "--listing-make X, --details-full [--make X], --details-update"
            )
    finally:
        browser.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="turbo_market local scraper (5-mode listing/details split)",
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--listing-full",
        action="store_true",
        help="Listing pass for all makes (Phase 1 + classify suspects + safety deactivate)",
    )
    mode_group.add_argument(
        "--listing-make",
        metavar="MAKE",
        help="Listing pass scoped to one make (e.g. --listing-make Toyota)",
    )
    mode_group.add_argument(
        "--details-full",
        action="store_true",
        help=(
            "Details pass over every row in DB (FIFO by vehicle.id). "
            "Combine with --make X to scope to one make."
        ),
    )
    mode_group.add_argument(
        "--details-update",
        action="store_true",
        help=(
            "Details pass over only rows flagged needs_detail_refresh=TRUE. "
            "Clears the flag after each successful row."
        ),
    )
    parser.add_argument(
        "--make",
        help="Used with --details-full to scope FIFO iteration to one make",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Force headless mode — overrides SCRAPER_MODE in .env (use for cron)",
    )
    args = parser.parse_args()

    if args.headless:
        os.environ["SCRAPER_MODE"] = "headless"

    if args.make and not args.details_full:
        parser.error("--make is only valid with --details-full")

    run(
        listing_full=args.listing_full,
        listing_make=args.listing_make,
        details_full=args.details_full,
        details_update=args.details_update,
        target_make=args.make,
    )
