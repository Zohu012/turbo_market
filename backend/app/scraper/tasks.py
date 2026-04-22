"""
Celery tasks for scraping turbo.az.

Worker setup:
  Listing queue:  celery -A app.scraper.celery_app worker -Q listing --concurrency=1
  Detail queue:   celery -A app.scraper.celery_app worker -Q detail --concurrency=3
  Beat scheduler: celery -A app.scraper.celery_app beat
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from celery import shared_task

from app.scraper.celery_app import celery_app
from app.scraper.browser import BrowserManager
from app.scraper.listing_scraper import get_all_makes, scrape_make_pages
from app.scraper.detail_scraper import scrape_detail
from app.scraper.pipeline import (
    get_sync_conn,
    upsert_listing,
    update_vehicle_detail,
    mark_delisted,
)
from app.scraper.lifecycle import run_lifecycle_check_sync
from app.scraper.seller_classifier import reclassify_sellers
from app.config import settings

log = logging.getLogger(__name__)

# Module-level browser instance per worker process
_browser: Optional[BrowserManager] = None


def get_browser() -> BrowserManager:
    global _browser
    if _browser is None:
        _browser = BrowserManager()
        _browser.start()
    return _browser


def _update_job_status(conn, job_id: int, status: str, **kwargs):
    if not job_id:
        return
    fields = {"status": status, **kwargs}
    set_clause = ", ".join(f"{k} = %({k})s" for k in fields)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE scrape_jobs SET {set_clause} WHERE id = %(job_id)s",
            {**fields, "job_id": job_id},
        )
    conn.commit()


def _create_job(conn, job_type: str, triggered_by: str, target_make=None, target_model=None, celery_task_id=None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scrape_jobs
              (job_type, status, triggered_by, target_make, target_model, celery_task_id, created_at)
            VALUES (%s, 'running', %s, %s, %s, %s, %s) RETURNING id
            """,
            (job_type, triggered_by, target_make, target_model, celery_task_id, datetime.now(timezone.utc)),
        )
        job_id = cur.fetchone()[0]
    conn.commit()
    return job_id


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def fetch_detail(self, vehicle_id: int, url: str, job_id: Optional[int] = None):
    """Fetch vehicle detail page and update DB record.

    If the detail page indicates the listing was delisted, mark the vehicle
    inactive without overwriting the rest of its data. Otherwise apply the
    full detail payload.
    """
    try:
        browser = get_browser()
        page = browser.new_page()
        try:
            detail = scrape_detail(page, url)
        finally:
            browser.close_page(page)

        if not detail:
            return

        conn = get_sync_conn()
        try:
            if detail.get("delisted"):
                mark_delisted(conn, vehicle_id)
            else:
                update_vehicle_detail(conn, vehicle_id, detail)
        finally:
            conn.close()
    except Exception as exc:
        log.error(f"fetch_detail failed for {url}: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=2)
def scrape_make_task(self, make: dict, job_id: Optional[int] = None) -> dict:
    """Scrape all listing pages for one make, upsert vehicles."""
    browser = get_browser()
    page = browser.get_page()
    conn = get_sync_conn()

    counters = {"found": 0, "new": 0, "updated": 0}
    live_ids: list[int] = []

    try:
        vehicles = scrape_make_pages(page, make)
        counters["found"] = len(vehicles)

        for v in vehicles:
            live_ids.append(v["turbo_id"])
            vehicle_id, action, _, needs_detail = upsert_listing(conn, v)
            if action == "new":
                counters["new"] += 1
            elif action == "updated":
                counters["updated"] += 1
            # Queue detail fetch whenever the listing is new OR turbo.az's
            # own "Yeniləndi" timestamp moved. Unchanged rows with the same
            # timestamp skip the detail phase entirely.
            if needs_detail:
                fetch_detail.apply_async(
                    args=[vehicle_id, v["url"], job_id],
                    queue="detail",
                )

        if job_id:
            _update_job_status(
                conn,
                job_id,
                status="running",
                listings_found=counters["found"],
                listings_new=counters["new"],
                listings_updated=counters["updated"],
            )
    except Exception as exc:
        log.error(f"scrape_make_task failed for {make['name']}: {exc}")
        conn.close()
        raise self.retry(exc=exc)
    finally:
        conn.close()

    return {"make": make["name"], "live_ids": live_ids, **counters}


@celery_app.task(bind=True)
def lifecycle_check_task(self, results: list[dict], job_id: Optional[int] = None):
    """
    Called after all make scrape tasks complete (chord callback).
    Deactivates vehicles not seen in this run.
    """
    # Collect all live turbo_ids from make results
    live_ids: set[int] = set()
    total_found = 0
    total_new = 0
    total_updated = 0

    for r in results:
        if isinstance(r, dict):
            live_ids.update(r.get("live_ids", []))
            total_found += r.get("found", 0)
            total_new += r.get("new", 0)
            total_updated += r.get("updated", 0)

    conn = get_sync_conn()
    deactivated = run_lifecycle_check_sync(conn, live_ids)
    try:
        # Re-derive shop/dealer/private classification from the new state of
        # the world. Cheap — three bulk UPDATEs, one pass per scrape.
        reclassify_sellers(conn)
        _update_job_status(
            conn,
            job_id,
            status="done",
            finished_at=datetime.now(timezone.utc),
            listings_found=total_found,
            listings_new=total_new,
            listings_updated=total_updated,
            listings_deactivated=deactivated,
        )
    finally:
        conn.close()

    log.info(
        f"Full scan complete: found={total_found} new={total_new} "
        f"updated={total_updated} deactivated={deactivated}"
    )


@celery_app.task(bind=True)
def daily_full_scan(self):
    """Scheduled task: scrape all makes + lifecycle check."""
    from celery import chord

    conn = get_sync_conn()
    job_id = _create_job(conn, "full_scan", "scheduler", celery_task_id=self.request.id)
    conn.close()

    browser = get_browser()
    page = browser.get_page()
    makes = get_all_makes(page)
    log.info(f"daily_full_scan: found {len(makes)} makes, job_id={job_id}")

    make_tasks = [scrape_make_task.s(make, job_id) for make in makes]
    chord(make_tasks)(lifecycle_check_task.s(job_id))


@celery_app.task(bind=True)
def on_demand_scan(self, job_id: int, target_make: Optional[str] = None, target_model: Optional[str] = None):
    """On-demand scan triggered by admin API."""
    from celery import chord

    browser = get_browser()
    page = browser.get_page()
    all_makes = get_all_makes(page)

    if target_make:
        makes = [m for m in all_makes if m["name"].lower() == target_make.lower()]
        if not makes:
            log.warning(f"on_demand_scan: make '{target_make}' not found")
            conn = get_sync_conn()
            _update_job_status(conn, job_id, "failed", error_message=f"Make '{target_make}' not found")
            conn.close()
            return
    else:
        makes = all_makes

    make_tasks = [scrape_make_task.s(make, job_id) for make in makes]
    chord(make_tasks)(lifecycle_check_task.s(job_id))
