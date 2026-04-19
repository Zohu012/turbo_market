#!/usr/bin/env python3
"""
Standalone local scraper — runs full turbo.az scan and writes to managed Postgres.
Run from the backend/ directory:
    python scripts/run_local.py
    python scripts/run_local.py --make Toyota     # single make
    python scripts/run_local.py --headless        # headless mode (for cron)
    python scripts/run_local.py --fresh           # ignore checkpoint, start from first make
    python scripts/run_local.py --details-only    # skip Phase 1, only fetch missing details
    python scripts/run_local.py --skip-details    # only Phase 1 (listings), no detail pages
    python scripts/run_local.py --skip-lifecycle  # no sold/removed deactivation

Checkpoint/resume:
    Phase 1: saves last completed make to scraper_checkpoint.txt; next run skips done makes.
             Cleared when Phase 1 finishes cleanly. --fresh ignores it.
    Phase 2: queries DB for active vehicles with raw_detail_json IS NULL — automatically
             resumes after crash since finished vehicles have the column populated.
             Completion = zero rows match that query.

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
from app.scraper.pipeline import get_sync_conn, upsert_listing, update_vehicle_detail
from app.scraper.lifecycle import run_lifecycle_check_sync


CHECKPOINT_FILE = Path(__file__).parent.parent / "scraper_checkpoint.txt"


def load_checkpoint() -> str | None:
    if CHECKPOINT_FILE.exists():
        name = CHECKPOINT_FILE.read_text(encoding="utf-8").strip()
        return name or None
    return None


def save_checkpoint(make_name: str) -> None:
    CHECKPOINT_FILE.write_text(make_name, encoding="utf-8")


def clear_checkpoint() -> None:
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()


def fetch_pending_details(conn, target_make: str = None) -> list[tuple[int, str]]:
    """Vehicles that still need Phase 2 (detail page) — auto-resumable via DB state."""
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

    try:
        page = browser.get_page()
        live_ids: set[int] = set()

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
                    return
            else:
                makes = all_makes
                if fresh:
                    clear_checkpoint()
                else:
                    last = load_checkpoint()
                    if last:
                        idx = next(
                            (i for i, m in enumerate(makes) if m["name"] == last),
                            -1,
                        )
                        if idx >= 0:
                            skipped = idx + 1
                            makes = makes[skipped:]
                            log.info(
                                f"Resuming after last completed make '{last}' — "
                                f"skipping {skipped} already-done, {len(makes)} remaining"
                            )
                        else:
                            log.warning(
                                f"Checkpoint make '{last}' not in current list — ignoring"
                            )

            log.info(f"Phase 1: scanning {len(makes)} make(s)")

            for make in makes:
                log.info(f"[make] {make['name']}")
                committed = {"n": 0}

                def _commit_page(vehicles_on_page):
                    # Per-page commit — preserves earlier pages if a later
                    # page times out. Counter is closed-over so we can log
                    # how many were saved even if the make errors out.
                    for v in vehicles_on_page:
                        live_ids.add(v["turbo_id"])
                        upsert_listing(conn, v)
                    committed["n"] += len(vehicles_on_page)

                try:
                    vehicles = scrape_make_pages(
                        page, make, on_page_complete=_commit_page
                    )
                    log.info(
                        f"  {make['name']}: {len(vehicles)} found, "
                        f"{committed['n']} committed"
                    )
                except Exception as e:
                    log.error(
                        f"  {make['name']} failed after committing "
                        f"{committed['n']} vehicles: {e}"
                    )
                    continue
                finally:
                    if not target_make:
                        save_checkpoint(make["name"])

            if not target_make:
                clear_checkpoint()
        else:
            log.info("Phase 1 skipped (--details-only)")

        # ── Phase 2: detail pages (driven by DB state — auto-resumable) ──────
        if skip_details:
            log.info("Phase 2 skipped (--skip-details)")
        else:
            pending = fetch_pending_details(conn, target_make)
            log.info(f"Phase 2: {len(pending)} vehicles pending details")

            # Reuse ONE detail page for the whole phase — opening a fresh
            # tab per vehicle defeats Cloudflare session reuse and makes
            # manual checkbox clicks useless (user clicks one tab, next
            # URL opens a different tab). One persistent tab means one
            # solved challenge = all subsequent navigations clean.
            detail_page = browser.new_page()
            try:
                for i, (vehicle_id, url) in enumerate(pending, 1):
                    if i % 50 == 0 or i == len(pending):
                        log.info(f"  Details: {i}/{len(pending)}")
                    try:
                        detail = scrape_detail(detail_page, url)
                        if detail:
                            update_vehicle_detail(conn, vehicle_id, detail)
                    except Exception as e:
                        log.warning(f"  Detail fetch failed for {url}: {e}")
            finally:
                browser.close_page(detail_page)

            # Completion check — how many still un-detailed after the run?
            remaining = fetch_pending_details(conn, target_make)
            if remaining:
                log.warning(
                    f"Phase 2 done — {len(remaining)} vehicles still missing details "
                    f"(likely detail-page failures; re-run to retry)"
                )
            else:
                log.info("Phase 2 done — all active vehicles have detail data")

        # ── Phase 3: lifecycle check (only on full scan) ─────────────────────
        if target_make or details_only or skip_lifecycle:
            if skip_lifecycle:
                log.info("Phase 3 skipped (--skip-lifecycle)")
        else:
            log.info(f"Phase 3: lifecycle check on {len(live_ids)} live IDs...")
            deactivated = run_lifecycle_check_sync(conn, live_ids)
            log.info(f"Deactivated {deactivated} sold/removed vehicles")

        log.info("=== Scan complete ===")

    finally:
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
        help="Skip Phase 2 (detail pages) — listings only",
    )
    parser.add_argument(
        "--skip-lifecycle",
        action="store_true",
        help="Skip Phase 3 (sold/removed deactivation)",
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
