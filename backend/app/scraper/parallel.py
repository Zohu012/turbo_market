"""
Parallel scraper runners — ThreadPoolExecutor with per-worker Playwright.

Each worker thread owns its own Playwright instance + persistent BrowserContext +
Page (Playwright sync API isn't safe to share across threads). Per-worker profile
directories under `browser_profile/worker_{N}/` let each worker accumulate its
own Cloudflare trust independently.

Three entry points:
  - run_details_parallel(mode, target_make, ...)     → details_full / details_update
  - run_listing_parallel(target_make, ...)            → listing_full / listing_make
  - WorkerBrowser                                     → low-level, used by both

Checkpoint semantics (chunk-based):
  Rows are processed in chunks of `chunk_size`. After every chunk fully drains
  (success, delisted, or load_failed), the checkpoint is advanced to the chunk's
  highest vehicle.id. Worst-case loss on Ctrl-C is one chunk (~100 rows = ~40s
  of work). Per-row failures are appended to `scraper_failed_<key>.txt` and
  re-prepended on the next run.
"""
from __future__ import annotations

import concurrent.futures
import logging
import signal
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

from app.config import settings
from app.scraper.browser import BrowserManager
from app.scraper.detail_scraper import scrape_detail
from app.scraper.listing_scraper import get_all_makes, scrape_make_pages
from app.scraper.pipeline import (
    get_sync_conn,
    upsert_listing,
    update_vehicle_detail,
    mark_delisted,
    persist_view_count,
    clear_needs_detail_refresh,
)
from app.scraper.checkpoint import (
    save_details_progress,
    load_details_progress,
    clear_checkpoint,
    save_listing_progress,
    load_listing_progress,
    load_failed_ids,
    append_failed_ids,
    clear_failed_ids,
)
from app.scraper.classifier import select_delist_suspects
from app.scraper.lifecycle import increment_misses_for_ids, run_safety_deactivate
from app.scraper.session import create_session, finish_session, update_session

log = logging.getLogger(__name__)

# Where per-worker persistent profiles live. One sibling dir per worker so each
# accumulates its own Cloudflare trust without stepping on the others.
BROWSER_PROFILE_DIR = Path(__file__).parent.parent.parent / "browser_profile"

# Playwright sync_api creates an internal asyncio event loop on start(); calling
# it from multiple threads simultaneously on Windows causes "thread initializer
# failed" and breaks the entire pool. Serialize browser startups with this lock.
#
# Note: Playwright objects (Playwright, Browser, Context, Page) are thread-bound
# via greenlets. They CANNOT be shared across threads — every worker must own
# its own full stack. In CDP mode we open multiple parallel CDP connections
# against the same Chrome instance (Chrome supports this fine).
_PLAYWRIGHT_INIT_LOCK = threading.Lock()

# After this many consecutive load failures, a worker is considered poisoned
# (stuck CF challenge, bad IP, etc.) and its context is torn down + recreated.
_WORKER_RESET_THRESHOLD = 5


class WorkerBrowser:
    """One Playwright instance + persistent context + page per worker thread.

    Sync-API Playwright isn't safe to share across threads — every worker
    must have its own. Each worker gets its own persistent profile dir
    (`browser_profile/worker_{i}/`) so Cloudflare trust accumulates per-worker.
    """

    def __init__(self, worker_id: int):
        self.worker_id = worker_id
        self._playwright = None
        self._browser = None  # only set in CDP mode
        self._context = None
        self._page = None

    def start(self) -> "WorkerBrowser":
        if settings.scraper_mode == "cdp":
            # Each worker opens its OWN CDP connection to the user's Chrome.
            # Playwright objects are thread-bound (greenlet) — sharing across
            # workers raises "Cannot switch to a different thread". Multiple
            # CDP connections to one Chrome instance is supported.
            with _PLAYWRIGHT_INIT_LOCK:
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.connect_over_cdp(
                    settings.cdp_url
                )
            # Reuse the existing context (preserves the user's CF trust /
            # cookies). Each worker opens its own Page on it; pages share
            # cookies but are independent objects.
            self._context = (
                self._browser.contexts[0]
                if self._browser.contexts
                else self._browser.new_context()
            )
            self._page = self._context.new_page()
            BrowserManager.block_media(self._page)
            return self

        with _PLAYWRIGHT_INIT_LOCK:
            self._playwright = sync_playwright().start()
        profile_dir = BROWSER_PROFILE_DIR / f"worker_{self.worker_id}"
        profile_dir.mkdir(parents=True, exist_ok=True)

        proxy = None
        if settings.proxy_server:
            proxy = {
                "server": settings.proxy_server,
                "username": settings.proxy_username,
                "password": settings.proxy_password,
            }

        self._context = self._playwright.chromium.launch_persistent_context(
            str(profile_dir),
            headless=True,
            proxy=proxy,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            timeout=60000,
        )

        try:
            from playwright_stealth import stealth_sync
            self._context.on("page", stealth_sync)
            for p in self._context.pages:
                stealth_sync(p)
        except ImportError:
            pass

        self._page = self._context.new_page()
        BrowserManager.block_media(self._page)
        return self

    def page(self):
        if self._page is None:
            raise RuntimeError("WorkerBrowser not started")
        return self._page

    def reset(self) -> None:
        """Tear down + restart this worker's browser. Used after a streak of
        load failures suggests the worker is shadow-banned."""
        log.warning(f"  worker {self.worker_id}: resetting context")
        self.stop()
        self.start()

    def stop(self) -> None:
        # Close in inside-out order. For CDP, browser.close() disconnects the
        # CDP session but does NOT terminate the user's Chrome process.
        try:
            if self._page:
                self._page.close()
        except Exception:
            pass
        if settings.scraper_mode == "cdp":
            try:
                if self._browser:
                    self._browser.close()
            except Exception:
                pass
        else:
            try:
                if self._context:
                    self._context.close()
            except Exception:
                pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._page = self._context = self._browser = self._playwright = None


# ── Details parallel runner ────────────────────────────────────────────────


def run_details_parallel(
    mode: str,
    target_make: Optional[str] = None,
    worker_count: int = 8,
    chunk_size: int = 100,
) -> dict:
    """Parallel version of the details pass.

      mode="full"             FIFO every vehicle in DB
      mode="full" + make      FIFO every vehicle for that make
      mode="update"           FIFO only rows with needs_detail_refresh=TRUE

    Returns counters dict: {processed, delisted, load_failed, total}.
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

    main_conn = get_sync_conn()
    try:
        with main_conn.cursor() as cur:
            cur.execute(sql, params)
            rows: list[tuple[int, str]] = [(r[0], r[1]) for r in cur.fetchall()]
    finally:
        main_conn.close()

    if not rows:
        log.info(f"Details parallel ({mode}): nothing to do")
        return {"processed": 0, "delisted": 0, "load_failed": 0, "total": 0}

    # Resume from checkpoint — drop ids ≤ last completed.
    last_id = load_details_progress(ckpt_key)
    if last_id is not None:
        before = len(rows)
        rows = [(vid, url) for vid, url in rows if vid > last_id]
        skipped = before - len(rows)
        if skipped:
            log.info(
                f"Resuming {ckpt_key} past id={last_id} "
                f"(skipped {skipped} already-done)"
            )

    # Re-prepend retry queue from previous failed rows. We re-fetch their URLs
    # via a single SQL roundtrip so callers can re-attempt cleanly.
    retry_ids = load_failed_ids(ckpt_key)
    if retry_ids:
        retry_set = set(retry_ids)
        retry_conn = get_sync_conn()
        try:
            with retry_conn.cursor() as cur:
                cur.execute(
                    "SELECT id, url FROM vehicles WHERE id = ANY(%s)",
                    (list(retry_set),),
                )
                retry_rows = [(r[0], r[1]) for r in cur.fetchall()]
        finally:
            retry_conn.close()
        # Drop these from the main queue so they're not duplicated.
        rows = [(vid, url) for vid, url in rows if vid not in retry_set]
        rows = retry_rows + rows
        log.info(f"Re-queued {len(retry_rows)} failed row(s) from previous run")
        clear_failed_ids(ckpt_key)

    total = len(rows)
    log.info(
        f"Details parallel ({mode}): {total} row(s), "
        f"workers={worker_count}, chunk_size={chunk_size}"
    )

    # ── Pre-flight check: try starting one browser in the main thread first.
    # If this fails, parallel mode has no chance — fail loudly with full
    # traceback rather than silently marking every row as load_failed.
    log.info("Pre-flight: starting one browser to verify environment...")
    try:
        _preflight = WorkerBrowser(worker_id=0).start()
        _preflight.stop()
        log.info("Pre-flight OK — browser launches cleanly.")
    except Exception as e:
        log.error(
            "Pre-flight FAILED — WorkerBrowser cannot launch. "
            "Aborting parallel run.\n"
            f"Exception: {type(e).__name__}: {e}\n"
            f"Traceback:\n{traceback.format_exc()}"
        )
        raise RuntimeError(
            f"Parallel pre-flight failed: {type(e).__name__}: {e}"
        ) from e

    # ── Worker state ──
    thread_local = threading.local()
    init_success_count = {"n": 0}
    init_success_lock = threading.Lock()
    worker_id_counter = {"n": 0}
    worker_id_lock = threading.Lock()
    worker_browsers: list[WorkerBrowser] = []
    worker_conns: list = []
    workers_lock = threading.Lock()

    def _init_worker():
        with worker_id_lock:
            wid = worker_id_counter["n"]
            worker_id_counter["n"] += 1
        log.info(f"  worker {wid}: starting...")
        try:
            browser = WorkerBrowser(wid).start()
        except Exception as e:
            log.error(
                f"  worker {wid}: browser init FAILED — "
                f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            )
            thread_local.browser = None
            thread_local.conn = None
            thread_local.consecutive_failures = 0
            return
        try:
            conn = get_sync_conn()
        except Exception as e:
            log.error(
                f"  worker {wid}: DB connection FAILED — "
                f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            )
            try:
                browser.stop()
            except Exception:
                pass
            thread_local.browser = None
            thread_local.conn = None
            thread_local.consecutive_failures = 0
            return
        with workers_lock:
            worker_browsers.append(browser)
            worker_conns.append(conn)
        thread_local.browser = browser
        thread_local.conn = conn
        thread_local.consecutive_failures = 0
        with init_success_lock:
            init_success_count["n"] += 1
        log.info(f"  worker {wid}: ready ({init_success_count['n']}/{worker_count})")

    # ── Stop handling ──
    stop_event = threading.Event()
    is_main_thread = threading.current_thread() is threading.main_thread()
    old_handler = None
    if is_main_thread:
        def _sigint(_sig, _frm):
            if not stop_event.is_set():
                log.warning("Stop requested — finishing in-flight chunk...")
            stop_event.set()
        old_handler = signal.signal(signal.SIGINT, _sigint)

    counters = {"processed": 0, "delisted": 0, "load_failed": 0}
    counters_lock = threading.Lock()
    failed_in_chunk: list[int] = []
    failed_lock = threading.Lock()

    def _process_row(vehicle_id: int, url: str):
        if stop_event.is_set():
            return
        browser = thread_local.browser
        conn = thread_local.conn
        if browser is None:
            with counters_lock:
                counters["load_failed"] += 1
            with failed_lock:
                failed_in_chunk.append(vehicle_id)
            return
        page = browser.page()

        try:
            detail = scrape_detail(page, url)
        except Exception as e:
            log.warning(f"  Detail fetch failed for {url}: {e}")
            with counters_lock:
                counters["load_failed"] += 1
            with failed_lock:
                failed_in_chunk.append(vehicle_id)
            thread_local.consecutive_failures += 1
            if thread_local.consecutive_failures >= _WORKER_RESET_THRESHOLD:
                browser.reset()
                thread_local.consecutive_failures = 0
            return

        if not detail:
            with counters_lock:
                counters["load_failed"] += 1
            with failed_lock:
                failed_in_chunk.append(vehicle_id)
            thread_local.consecutive_failures += 1
            if thread_local.consecutive_failures >= _WORKER_RESET_THRESHOLD:
                browser.reset()
                thread_local.consecutive_failures = 0
            return

        thread_local.consecutive_failures = 0

        if detail.get("delisted"):
            try:
                mark_delisted(conn, vehicle_id)
                scraped_vc = detail.get("view_count_scraped")
                if scraped_vc is not None:
                    persist_view_count(conn, vehicle_id, scraped_vc)
                with counters_lock:
                    counters["delisted"] += 1
            except Exception as e:
                log.warning(
                    f"  delisted handling failed for vehicle {vehicle_id}: {e}"
                )
                return
            try:
                update_vehicle_detail(
                    conn, vehicle_id, detail,
                    preserve_collections_if_shorter=True,
                )
            except Exception as e:
                log.warning(
                    f"  delisted spec backfill failed for vehicle {vehicle_id}: {e}"
                )
        else:
            try:
                update_vehicle_detail(
                    conn,
                    vehicle_id,
                    detail,
                    preserve_collections_if_shorter=(mode == "full"),
                )
                with counters_lock:
                    counters["processed"] += 1
            except Exception as e:
                log.warning(
                    f"  update_vehicle_detail failed for vehicle {vehicle_id}: {e}"
                )
                return

        if mode == "update":
            try:
                clear_needs_detail_refresh(conn, vehicle_id)
            except Exception as e:
                log.warning(
                    f"  clear_needs_detail_refresh failed for vehicle "
                    f"{vehicle_id}: {e}"
                )

    # ── Chunked execution ──
    try:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=worker_count, initializer=_init_worker
        ) as executor:
            done = 0
            for chunk_start in range(0, total, chunk_size):
                if stop_event.is_set():
                    log.info("Stop requested before chunk start — exiting.")
                    break
                chunk = rows[chunk_start:chunk_start + chunk_size]
                futures = [
                    executor.submit(_process_row, vid, url) for vid, url in chunk
                ]
                for f in concurrent.futures.as_completed(futures):
                    try:
                        f.result()
                    except Exception as e:
                        log.warning(f"  worker future raised: {e}")

                # Advance checkpoint to highest id in the completed chunk.
                # Even rows that load_failed are tracked in the failed-ids
                # file and will be retried on the next run.
                max_id = max(vid for vid, _ in chunk)
                save_details_progress(ckpt_key, max_id)

                # Flush this chunk's failures to disk for next-run retry.
                with failed_lock:
                    if failed_in_chunk:
                        append_failed_ids(ckpt_key, failed_in_chunk)
                        failed_in_chunk.clear()

                done += len(chunk)
                log.info(
                    f"  Details: {done}/{total} "
                    f"(processed={counters['processed']} "
                    f"delisted={counters['delisted']} "
                    f"load_failed={counters['load_failed']})"
                )

                # Bail out early if the first chunk shows ALL rows failing.
                # Every load = ~100ms minimum; if 100 rows all "fail" in
                # well under that, workers are silently skipping and we'd
                # otherwise burn through the whole queue trashing the
                # checkpoint. Force a stop so the user sees the issue.
                if done == len(chunk) and counters["processed"] == 0 and counters["delisted"] == 0:
                    log.error(
                        f"ABORT: first chunk had 0 successes / "
                        f"{counters['load_failed']} failures. "
                        f"Workers initialized: {init_success_count['n']}/{worker_count}. "
                        "Check 'browser init FAILED' / 'DB connection FAILED' "
                        "messages above for the root cause."
                    )
                    stop_event.set()
                    break

    finally:
        # Teardown order: futures already drained by executor exit.
        with workers_lock:
            for b in worker_browsers:
                b.stop()
            for c in worker_conns:
                try:
                    c.close()
                except Exception:
                    pass
        if is_main_thread and old_handler is not None:
            signal.signal(signal.SIGINT, old_handler)

    if not stop_event.is_set():
        clear_checkpoint(ckpt_key)

    log.info(
        f"Details parallel ({mode}) complete — "
        f"processed={counters['processed']} "
        f"delisted={counters['delisted']} "
        f"load_failed={counters['load_failed']}"
    )
    return {**counters, "total": total}


# ── Listing parallel runner ────────────────────────────────────────────────


def run_listing_parallel(
    target_make: Optional[str] = None,
    worker_count: int = 8,
) -> dict:
    """Parallel version of the listing pass — one worker per make.

    Pages within a make stay serial (pagination is order-dependent for the
    "stop on first known url" optimization in scrape_make_pages). The win
    comes from running 8 makes concurrently — Chevrolet (~85 pages), BMW,
    Mercedes, etc. all chip away at once.

    Returns counters dict: {found, new, updated, deactivated}.
    """
    ckpt_key = "listing_make" if target_make else "listing_full"

    # Phase 0: discover makes via a temporary single browser (cheap).
    discovery = WorkerBrowser(worker_id=999).start()
    try:
        all_makes = get_all_makes(discovery.page())
    finally:
        discovery.stop()

    if target_make:
        makes = [m for m in all_makes if m["name"].lower() == target_make.lower()]
        if not makes:
            log.error(f"Make '{target_make}' not found.")
            return {"found": 0, "new": 0, "updated": 0, "deactivated": 0}
    else:
        makes = all_makes

    # Resume: drop already-done makes (those before the saved make in the
    # original order). We don't try to resume mid-make in parallel mode —
    # the make is re-scraped from page 1.
    last_make, _ = load_listing_progress(ckpt_key)
    if last_make:
        idx = next(
            (i for i, m in enumerate(makes) if m["name"] == last_make), -1
        )
        if idx >= 0:
            skipped = idx + 1
            makes = makes[idx + 1:]
            log.info(
                f"Resuming after completed make '{last_make}' — "
                f"skipping {skipped}, {len(makes)} remaining"
            )

    if not makes:
        log.info("Listing parallel: nothing to do")
        return {"found": 0, "new": 0, "updated": 0, "deactivated": 0}

    # Session bookkeeping (single row, like the serial path).
    main_conn = get_sync_conn()
    session_id, session_start = create_session(
        main_conn,
        job_type="listing_make" if target_make else "listing_full",
        triggered_by="parallel",
        target_make=target_make,
    )
    log.info(
        f"Session {session_id} started at {session_start.isoformat()} "
        f"(parallel, workers={worker_count}, makes={len(makes)})"
    )

    counters = {"found": 0, "new": 0, "updated": 0, "deactivated": 0}
    counters_lock = threading.Lock()

    thread_local = threading.local()
    worker_id_counter = {"n": 0}
    worker_id_lock = threading.Lock()
    worker_browsers: list[WorkerBrowser] = []
    worker_conns: list = []
    workers_lock = threading.Lock()

    def _init_worker():
        with worker_id_lock:
            wid = worker_id_counter["n"]
            worker_id_counter["n"] += 1
        log.info(f"  listing worker {wid}: starting...")
        try:
            browser = WorkerBrowser(wid).start()
        except Exception as e:
            log.error(f"  listing worker {wid}: browser init failed — {e}")
            thread_local.browser = None
            thread_local.conn = None
            return
        conn = get_sync_conn()
        with workers_lock:
            worker_browsers.append(browser)
            worker_conns.append(conn)
        thread_local.browser = browser
        thread_local.conn = conn

    def _process_make(make: dict):
        browser = thread_local.browser
        conn = thread_local.conn
        if browser is None:
            log.error(f"  {make['name']}: skipped — worker has no browser")
            return
        page = browser.page()
        committed_n = 0
        local_counters = {"found": 0, "new": 0, "updated": 0}

        def _commit_page(vehicles_on_page, page_num):
            nonlocal committed_n
            for v in vehicles_on_page:
                _vid, action, _, _needs = upsert_listing(
                    conn, v, session_start=session_start
                )
                local_counters["found"] += 1
                if action == "new":
                    local_counters["new"] += 1
                elif action == "updated":
                    local_counters["updated"] += 1
            committed_n += len(vehicles_on_page)

        try:
            vehicles = scrape_make_pages(
                page, make, start_page=1, on_page_complete=_commit_page
            )
            log.info(
                f"  {make['name']}: {len(vehicles)} found, "
                f"{committed_n} committed"
            )
        except Exception as e:
            log.error(f"  {make['name']} failed: {e}")
        finally:
            with counters_lock:
                counters["found"] += local_counters["found"]
                counters["new"] += local_counters["new"]
                counters["updated"] += local_counters["updated"]
            # Mark this make completed in the checkpoint so a crash mid-run
            # lets the next run skip already-done makes.
            save_listing_progress(ckpt_key, make["name"])

    session_status = "running"
    session_error: Optional[str] = None

    stop_event = threading.Event()
    is_main_thread = threading.current_thread() is threading.main_thread()
    old_handler = None
    if is_main_thread:
        def _sigint(_sig, _frm):
            if not stop_event.is_set():
                log.warning("Stop requested — letting current makes finish...")
            stop_event.set()
        old_handler = signal.signal(signal.SIGINT, _sigint)

    try:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=worker_count, initializer=_init_worker
        ) as executor:
            futures = []
            for make in makes:
                if stop_event.is_set():
                    break
                futures.append(executor.submit(_process_make, make))
            for f in concurrent.futures.as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    log.warning(f"  make future raised: {e}")

        if not stop_event.is_set():
            clear_checkpoint(ckpt_key)

        update_session(
            main_conn,
            session_id,
            listings_found=counters["found"],
            listings_new=counters["new"],
            listings_updated=counters["updated"],
        )

        # Phase 2: classify delist-suspects (single-threaded — DB-only).
        suspects = select_delist_suspects(main_conn, session_start, target_make)
        log.info(
            f"Phase 2: {len(suspects)} delist-suspect(s) flagged for detail refresh"
        )

        # Phase 3: two-miss safety deactivate.
        suspect_ids = [vid for vid, _ in suspects]
        if suspect_ids:
            bumped = increment_misses_for_ids(main_conn, suspect_ids)
            log.info(f"Phase 3: bumped missing_scan_count for {bumped} suspect(s)")
        deactivated = run_safety_deactivate(main_conn)
        counters["deactivated"] = deactivated
        log.info(f"Phase 3: deactivated {deactivated} vehicle(s) (>= 2 misses)")

        session_status = "done"
        log.info("=== Listing parallel pass complete ===")

    except Exception as e:
        session_status = "failed"
        session_error = f"{type(e).__name__}: {e}"
        log.exception("Listing parallel failed with unhandled exception")
        raise
    finally:
        with workers_lock:
            for b in worker_browsers:
                b.stop()
            for c in worker_conns:
                try:
                    c.close()
                except Exception:
                    pass
        if is_main_thread and old_handler is not None:
            signal.signal(signal.SIGINT, old_handler)
        try:
            finish_session(
                main_conn,
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
        main_conn.close()

    return counters
