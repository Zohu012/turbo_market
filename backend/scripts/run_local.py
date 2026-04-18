#!/usr/bin/env python3
"""
Standalone local scraper — runs full turbo.az scan and writes to managed Postgres.
Run from the backend/ directory:
    python scripts/run_local.py
    python scripts/run_local.py --make Toyota     # single make
    python scripts/run_local.py --headless        # headless mode (for cron)

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


def run(target_make: str = None):
    log.info("=== turbo_market local scraper starting ===")
    browser = BrowserManager()
    browser.start()
    conn = get_sync_conn()

    try:
        page = browser.get_page()
        all_makes = get_all_makes(page)

        if target_make:
            makes = [m for m in all_makes if m["name"].lower() == target_make.lower()]
            if not makes:
                log.error(
                    f"Make '{target_make}' not found. "
                    f"Available (first 10): {[m['name'] for m in all_makes[:10]]}..."
                )
                return
        else:
            makes = all_makes

        log.info(f"Scanning {len(makes)} make(s)")

        live_ids: set[int] = set()
        new_vehicles: list[tuple[int, str]] = []  # (vehicle_id, url)

        # Phase 1: listing scan
        for make in makes:
            log.info(f"→ {make['name']}")
            try:
                vehicles = scrape_make_pages(page, make)
                for v in vehicles:
                    live_ids.add(v["turbo_id"])
                    vehicle_id, action, _ = upsert_listing(conn, v)
                    if action == "new":
                        new_vehicles.append((vehicle_id, v["url"]))
                log.info(f"  {make['name']}: {len(vehicles)} found")
            except Exception as e:
                log.error(f"  {make['name']} failed: {e}")
                continue

        # Phase 2: detail pages for new vehicles
        log.info(f"Fetching details for {len(new_vehicles)} new vehicles...")
        for i, (vehicle_id, url) in enumerate(new_vehicles, 1):
            if i % 50 == 0:
                log.info(f"  Details: {i}/{len(new_vehicles)}")
            detail_page = browser.new_page()
            try:
                detail = scrape_detail(detail_page, url)
                if detail:
                    update_vehicle_detail(conn, vehicle_id, detail)
            except Exception as e:
                log.warning(f"  Detail fetch failed for {url}: {e}")
            finally:
                browser.close_page(detail_page)

        # Phase 3: lifecycle check (only on full scan, not single-make)
        if not target_make:
            log.info(f"Running lifecycle check on {len(live_ids)} live IDs...")
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
    args = parser.parse_args()

    if args.headless:
        os.environ["SCRAPER_MODE"] = "headless"

    run(target_make=args.make)
