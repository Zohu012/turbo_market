#!/usr/bin/env python3
"""
Local scraper UI — browser-based control panel for run_local.py.
Run from backend/:
    py -3.12 scripts/scraper_ui.py
Then open: http://localhost:8001

Five-mode listing/details split:
    1. Listing Full        — all makes, listing pages only
    2. Listing by make     — one make, listing pages only
    3. Details Full        — FIFO every row in DB
    4. Details Update      — only rows flagged needs_detail_refresh=TRUE
    5. Details by make     — FIFO every row of one make

Features:
    - Live stop button (SIGTERM, falls back to kill after 10s)
    - Tails scraper_local.log in real time
    - Shows checkpoint, DB stats, queued details count
"""
import json
import os
import subprocess
import sys
from collections import deque
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent
LOG_FILE = BACKEND_DIR / "scraper_local.log"
CHECKPOINT_FILE = BACKEND_DIR / "scraper_checkpoint.txt"

sys.path.insert(0, str(BACKEND_DIR))

# Load backend/.env before anything imports app.config (so settings pick it up).
from dotenv import load_dotenv  # noqa: E402
load_dotenv(BACKEND_DIR / ".env")

import uvicorn  # noqa: E402
from fastapi import FastAPI, Query  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402

from app.scraper.pipeline import get_sync_conn  # noqa: E402

app = FastAPI()
_proc: subprocess.Popen | None = None
_startup_warning: str | None = None


def _auto_migrate() -> None:
    """Apply pending alembic migrations on startup. Warns on failure but does not crash."""
    global _startup_warning
    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        command.upgrade(cfg, "head")
        print("[startup] alembic upgrade head OK")
    except Exception as e:
        msg = f"alembic upgrade failed: {e}"
        print(f"[startup] WARNING: {msg}")
        _startup_warning = msg


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>turbo_market scraper</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; background: #0f1115; color: #e3e6eb; }
  .wrap { max-width: 1100px; margin: 0 auto; padding: 20px; }
  h1 { margin: 0 0 16px; font-size: 20px; font-weight: 600; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .card { background: #1a1d23; border: 1px solid #2a2e36; border-radius: 8px; padding: 16px; }
  .card h2 { margin: 0 0 12px; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: #8b94a3; font-weight: 600; }
  .row { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
  button { background: #2d5bff; color: white; border: none; padding: 8px 14px; border-radius: 6px; font-size: 13px; cursor: pointer; font-weight: 500; }
  button:hover { background: #4670ff; }
  button:disabled { background: #3a3f48; color: #8b94a3; cursor: not-allowed; }
  button.danger { background: #c83644; }
  button.danger:hover { background: #e04858; }
  button.secondary { background: #3a3f48; }
  button.secondary:hover { background: #4a5058; }
  input, select { background: #0f1115; color: #e3e6eb; border: 1px solid #2a2e36; padding: 7px 10px; border-radius: 6px; font-size: 13px; }
  input:focus, select:focus { outline: none; border-color: #2d5bff; }
  .stat { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #2a2e36; font-size: 13px; }
  .stat:last-child { border-bottom: none; }
  .stat-label { color: #8b94a3; }
  .stat-value { font-weight: 600; font-variant-numeric: tabular-nums; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
  .badge.running { background: #1a4d2e; color: #4ade80; }
  .badge.idle { background: #3a3f48; color: #8b94a3; }
  pre.log { background: #050608; border: 1px solid #2a2e36; border-radius: 6px; padding: 10px; height: 420px; overflow-y: auto; font-size: 11.5px; line-height: 1.5; font-family: Consolas, Menlo, monospace; color: #c7cdd6; white-space: pre-wrap; word-break: break-word; margin: 0; }
  pre.log::-webkit-scrollbar { width: 8px; }
  pre.log::-webkit-scrollbar-thumb { background: #2a2e36; border-radius: 4px; }
  .log-err { color: #f87171; }
  .log-warn { color: #fbbf24; }
  .log-make { color: #60a5fa; font-weight: 600; }
  label { font-size: 12px; color: #8b94a3; margin-right: 4px; }
  @media (max-width: 800px) { .grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="wrap">
  <h1>turbo_market scraper <span id="status-badge" class="badge idle">idle</span></h1>

  <div class="grid">
    <div class="card">
      <h2>Controls</h2>
      <div class="row">
        <label style="color:#8b94a3;">All makes:</label>
        <button id="btn-listing-full" title="Listing pages only — scrape every make. Flags new/updated/delist-suspect rows for Details Update. Two-miss safety deactivates rows absent twice in a row.">Listing Full</button>
        <button id="btn-details-full" class="secondary" title="FIFO over every vehicle in DB (by vehicle.id). Live page → update detail; delisted page → mark_delisted; load failure → retry next run.">Details Full</button>
        <button id="btn-details-update" class="secondary" title="FIFO over rows flagged needs_detail_refresh=TRUE. Clears the flag after each row. Run after Listing Full to drain the queue.">Details Update</button>
      </div>
      <div class="row">
        <label>Make:</label>
        <select id="make-select" style="min-width: 160px;"><option value="">(load…)</option></select>
        <button id="btn-listing-make">Listing by make</button>
        <button id="btn-details-make" class="secondary">Details by make</button>
      </div>
      <div class="row" style="margin-top: 14px; padding-top: 12px; border-top: 1px solid #2a2e36;">
        <label style="color:#a78bfa; font-weight:600;">⚡ Parallel (fast):</label>
        <button id="btn-listing-parallel" style="background:#7c3aed;" title="Per-make parallelism — 8 workers scrape 8 makes concurrently. Always headless. Resumes from listing_full checkpoint at make boundaries.">Listing Full ⚡</button>
        <button id="btn-details-full-parallel" style="background:#7c3aed;" title="8 workers process the FIFO details queue concurrently. Targets ~5h for the full ~46k catalogue (vs ~62h serial). Per-make scoping when a make is selected. Chunk-based checkpoint advance every 100 rows.">Details Full ⚡</button>
        <button id="btn-details-update-parallel" style="background:#7c3aed;" title="8-worker parallel sweep of needs_detail_refresh=TRUE rows. Same fast path as Details Full ⚡, scoped to the refresh queue.">Details Update ⚡</button>
        <label style="margin-left:12px;">workers</label>
        <input type="number" id="parallel-workers" value="8" min="1" max="20" style="width:60px;" title="Number of concurrent Playwright workers (each with its own persistent profile dir). Conservative: 6-8. Aggressive: 12-16 (more RAM, higher CF risk)." />
      </div>
      <div class="row" style="margin-top: 14px;">
        <button id="btn-stop" class="danger" disabled>Stop</button>
      </div>
    </div>

    <div class="card">
      <h2>Status</h2>
      <div class="stat"><span class="stat-label">Checkpoint</span><span id="stat-checkpoint" class="stat-value">—</span></div>
      <div class="stat"><span class="stat-label">Active vehicles</span><span id="stat-active" class="stat-value">—</span></div>
      <div class="stat"><span class="stat-label">Inactive</span><span id="stat-inactive" class="stat-value">—</span></div>
      <div class="stat"><span class="stat-label">Queued for Details Update</span><span id="stat-pending" class="stat-value">—</span></div>
      <div class="stat"><span class="stat-label">Last DB update</span><span id="stat-last" class="stat-value">—</span></div>
      <div class="stat"><span class="stat-label">Process PID</span><span id="stat-pid" class="stat-value">—</span></div>
    </div>
  </div>

  <div class="card" style="margin-top: 16px;">
    <h2>Live log <span style="color:#8b94a3; font-weight:400; text-transform:none; letter-spacing:0; font-size:11px;">(scraper_local.log)</span>
      <label style="float:right;"><input type="checkbox" id="filter-input" checked> filter</label>
      <input type="text" id="filter-text" placeholder="filter (regex)" style="float:right; margin-right:8px; width:180px;" />
    </h2>
    <pre class="log" id="log">Waiting for output…</pre>
  </div>

  <div class="card" style="margin-top: 16px;">
    <h2>Inspect detail page <span style="color:#8b94a3; font-weight:400; text-transform:none; letter-spacing:0; font-size:11px;">(scraper must be stopped — also upserts the vehicle into DB)</span></h2>
    <div class="row">
      <input type="text" id="inspect-url" placeholder="https://turbo.az/autos/12345678-..." style="flex:1; min-width:280px;" />
      <button id="btn-inspect" class="secondary">Inspect &amp; save</button>
    </div>
    <pre class="log" id="inspect-out" style="height: 260px;">Paste a turbo.az detail URL and click &quot;Inspect &amp; save&quot;.
The page will be scraped, the vehicle inserted (if new) or updated in the DB,
and the parsed seller + tel: links will be shown for verification.</pre>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
let autoscroll = true;

$('log').addEventListener('scroll', e => {
  const el = e.target;
  autoscroll = (el.scrollHeight - el.scrollTop - el.clientHeight) < 30;
});

async function api(path, method='GET', body=null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  return r.json();
}

function colorize(line) {
  const esc = line.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  if (/ERROR/.test(line)) return '<span class="log-err">'+esc+'</span>';
  if (/WARNING/.test(line)) return '<span class="log-warn">'+esc+'</span>';
  if (/\\[make\\]/.test(line)) return '<span class="log-make">'+esc+'</span>';
  return esc;
}

async function refreshStatus() {
  try {
    const s = await api('/api/status');
    $('status-badge').textContent = s.running ? 'running' : 'idle';
    $('status-badge').className = 'badge ' + (s.running ? 'running' : 'idle');
    $('stat-checkpoint').textContent = s.checkpoint || '—';
    $('stat-active').textContent = s.active ?? '—';
    $('stat-inactive').textContent = s.inactive ?? '—';
    $('stat-pending').textContent = s.pending_details ?? '—';
    $('stat-last').textContent = s.last_update ? new Date(s.last_update).toLocaleString() : '—';
    $('stat-pid').textContent = s.pid || '—';

    ['btn-listing-full','btn-listing-make','btn-details-full','btn-details-update','btn-details-make',
     'btn-listing-parallel','btn-details-full-parallel','btn-details-update-parallel'
    ].forEach(id => $(id).disabled = s.running);
    $('btn-stop').disabled = !s.running;

    // Log
    let lines = s.log || [];
    const ftxt = $('filter-text').value;
    if ($('filter-input').checked && ftxt) {
      try {
        const re = new RegExp(ftxt, 'i');
        lines = lines.filter(l => re.test(l));
      } catch (e) {}
    }
    const logEl = $('log');
    if (lines.length > 0) {
      logEl.innerHTML = lines.map(colorize).join('');
      if (autoscroll) logEl.scrollTop = logEl.scrollHeight;
    } else if (!s.running) {
      logEl.textContent = 'No log yet — start a scan to see output.';
    }
  } catch (e) {
    console.error(e);
  }
}

async function loadMakes() {
  try {
    const r = await api('/api/makes');
    const sel = $('make-select');
    if (r.error) {
      sel.innerHTML = `<option value="">(DB error: ${r.error.slice(0, 60)})</option>`;
      console.error('makes error:', r.error);
      return;
    }
    if (!r.makes.length) {
      sel.innerHTML = '<option value="">(no vehicles in DB yet)</option>';
      return;
    }
    sel.innerHTML = '<option value="">— select make —</option>' +
      r.makes.map(m => `<option value="${m}">${m}</option>`).join('');
  } catch (e) {
    console.error(e);
  }
}

async function start(params) {
  const r = await api('/api/start?' + new URLSearchParams(params), 'POST');
  if (r.error) alert(r.error);
  refreshStatus();
}

$('btn-listing-full').onclick = () => start({ mode: 'listing-full' });
$('btn-listing-make').onclick = () => {
  const m = $('make-select').value;
  if (!m) { alert('Pick a make first'); return; }
  start({ mode: 'listing-make', make: m });
};
$('btn-details-full').onclick = () => {
  if (!confirm('Details Full re-scrapes every vehicle in DB (FIFO by id). This can take a long time. Safe to stop and resume via the details_full checkpoint. Continue?')) return;
  start({ mode: 'details-full' });
};
$('btn-details-update').onclick = () => start({ mode: 'details-update' });
$('btn-details-make').onclick = () => {
  const m = $('make-select').value;
  if (!m) { alert('Pick a make first'); return; }
  if (!confirm(`Details by make re-scrapes every "${m}" vehicle (FIFO by id). Safe to stop and resume. Continue?`)) return;
  start({ mode: 'details-make', make: m });
};

function _workers() {
  const n = parseInt($('parallel-workers').value || '8', 10);
  return (Number.isFinite(n) && n > 0 && n <= 20) ? n : 8;
}
$('btn-listing-parallel').onclick = () => {
  const m = $('make-select').value;
  if (!confirm(`Run Listing ${m ? `for "${m}" ` : ''}with ${_workers()} parallel workers? Always headless. Resumes from listing_full checkpoint at make boundaries.`)) return;
  start({ mode: m ? 'listing-make' : 'listing-full', make: m || '', parallel: '1', workers: _workers() });
};
$('btn-details-full-parallel').onclick = () => {
  const m = $('make-select').value;
  const target = m ? `every "${m}" vehicle` : 'every vehicle in DB';
  if (!confirm(`Details Full ⚡ re-scrapes ${target} with ${_workers()} parallel workers. ~5h for full ~46k. Safe to stop and resume (loses ≤100 rows of in-flight work). Continue?`)) return;
  start({ mode: m ? 'details-make' : 'details-full', make: m || '', parallel: '1', workers: _workers() });
};
$('btn-details-update-parallel').onclick = () => {
  if (!confirm(`Details Update ⚡ sweeps the needs_detail_refresh=TRUE queue with ${_workers()} parallel workers. Continue?`)) return;
  start({ mode: 'details-update', parallel: '1', workers: _workers() });
};
$('btn-stop').onclick = async () => {
  if (!confirm('Stop scraper?')) return;
  await api('/api/stop', 'POST');
  refreshStatus();
};

$('btn-inspect').onclick = async () => {
  const url = $('inspect-url').value.trim();
  if (!url) { alert('Paste a URL first'); return; }
  $('inspect-out').textContent = 'Loading… (this opens a browser page, takes a few seconds)';
  try {
    const r = await api('/api/inspect?url=' + encodeURIComponent(url));
    $('inspect-out').textContent = JSON.stringify(r, null, 2);
  } catch (e) {
    $('inspect-out').textContent = 'Error: ' + e.message;
  }
};

loadMakes();
refreshStatus();
setInterval(refreshStatus, 2000);
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML


@app.get("/api/makes")
def api_makes():
    try:
        with get_sync_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT make FROM vehicles WHERE make IS NOT NULL ORDER BY make"
            )
            return {"makes": [r[0] for r in cur.fetchall()]}
    except Exception as e:
        return JSONResponse({"makes": [], "error": str(e)}, status_code=500)


@app.get("/api/status")
def api_status():
    global _proc
    running = _proc is not None and _proc.poll() is None
    pid = _proc.pid if running else None

    checkpoint = None
    if CHECKPOINT_FILE.exists():
        checkpoint = CHECKPOINT_FILE.read_text(encoding="utf-8").strip() or None

    active = inactive = pending = 0
    last_update = None
    try:
        with get_sync_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  COUNT(*) FILTER (WHERE status = 'active'),
                  COUNT(*) FILTER (WHERE status = 'inactive'),
                  COUNT(*) FILTER (WHERE needs_detail_refresh = TRUE),
                  MAX(date_updated)
                FROM vehicles
                """
            )
            row = cur.fetchone()
            if row:
                active, inactive, pending, last_update = row
    except Exception as e:
        return JSONResponse(
            {
                "running": running,
                "pid": pid,
                "checkpoint": checkpoint,
                "log": [],
                "db_error": str(e),
            }
        )

    log_lines: list[str] = []
    if LOG_FILE.exists():
        try:
            with LOG_FILE.open("r", encoding="utf-8", errors="replace") as f:
                log_lines = list(deque(f, maxlen=300))
        except Exception:
            pass

    return {
        "running": running,
        "pid": pid,
        "checkpoint": checkpoint,
        "active": active,
        "inactive": inactive,
        "pending_details": pending,
        "last_update": last_update.isoformat() if last_update else None,
        "log": log_lines,
    }


@app.post("/api/start")
def api_start(
    mode: str = Query(...),
    make: str | None = Query(None),
    parallel: str | None = Query(None),
    workers: int | None = Query(None),
    chunk_size: int | None = Query(None),
):
    """mode: listing-full | listing-make | details-full | details-update | details-make

    `parallel` (truthy "1"/"true") routes to the multi-worker runner in
    backend/app/scraper/parallel.py. `workers` and `chunk_size` are forwarded
    when set; defaults are 8 and 100 respectively.
    """
    global _proc
    if _proc is not None and _proc.poll() is None:
        return JSONResponse({"error": "scraper is already running"}, status_code=400)

    args = [sys.executable, "scripts/run_local.py"]
    if mode == "listing-full":
        args += ["--listing-full"]
    elif mode == "listing-make":
        if not make:
            return JSONResponse({"error": "make is required"}, status_code=400)
        args += ["--listing-make", make]
    elif mode == "details-full":
        args += ["--details-full"]
    elif mode == "details-make":
        if not make:
            return JSONResponse({"error": "make is required"}, status_code=400)
        args += ["--details-full", "--make", make]
    elif mode == "details-update":
        args += ["--details-update"]
    else:
        return JSONResponse({"error": f"unknown mode: {mode}"}, status_code=400)

    if parallel and parallel.lower() in ("1", "true", "yes"):
        args.append("--parallel")
        if workers:
            args += ["--workers", str(workers)]
        if chunk_size:
            args += ["--chunk-size", str(chunk_size)]

    # Fresh start wipes the log so the UI shows only this run
    try:
        LOG_FILE.write_text("", encoding="utf-8")
    except Exception:
        pass

    _proc = subprocess.Popen(
        args,
        cwd=str(BACKEND_DIR),
        stdout=subprocess.DEVNULL,  # scraper already writes to scraper_local.log
        stderr=subprocess.DEVNULL,
    )
    return {"started": True, "pid": _proc.pid, "args": args[1:]}


def _extract_listing_fields_from_detail(page, url: str) -> dict | None:
    """
    Pull listing-card-equivalent fields from a detail page so we can
    upsert_listing when the vehicle isn't already in DB.

    Returns None if turbo_id can't be extracted (required field).
    """
    import re
    from app.scraper.listing_scraper import parse_price, to_price_azn

    m = re.search(r"/autos/(\d+)", url)
    if not m:
        return None
    turbo_id = int(m.group(1))

    # Make/model from URL slug (e.g. /autos/10313931-bmw-520 → BMW, 520)
    slug_m = re.search(r"/autos/\d+-([^/?#]+)", url)
    make = model = None
    if slug_m:
        parts = slug_m.group(1).split("-", 1)
        if parts:
            make = parts[0].replace("_", " ").title()
        if len(parts) > 1:
            model = parts[1].replace("-", " ").replace("_", " ")

    # Try h1 / breadcrumbs for a better make/model + year
    year = None
    try:
        h1_el = page.query_selector(
            "h1.product-title, .product-title, h1"
        )
        if h1_el:
            title_text = (h1_el.inner_text() or "").strip()
            ym = re.search(r"\b(19|20)\d{2}\b", title_text)
            if ym:
                year = int(ym.group(0))
    except Exception:
        pass

    # Price
    price = None
    currency = None
    try:
        price_el = page.query_selector(
            ".product-price__price, .product-price, .price"
        )
        if price_el:
            price, currency = parse_price(price_el.inner_text() or "")
    except Exception:
        pass

    return {
        "turbo_id": turbo_id,
        "make": make or "Unknown",
        "model": model or "Unknown",
        "year": year,
        "price": price,
        "currency": currency,
        "price_azn": to_price_azn(price, currency),
        "odometer": None,
        "odometer_type": None,
        "engine": None,
        "url": url,
    }


@app.get("/api/inspect")
def api_inspect(url: str):
    """
    Load a detail page, scrape it end-to-end, and upsert the vehicle into
    the DB (insert if new, update if existing). Returns parsed seller +
    tel: diagnostics for verification.

    Requires scraper NOT to be running (shares the CDP browser).
    """
    global _proc
    if _proc is not None and _proc.poll() is None:
        return JSONResponse(
            {"error": "stop the scraper before using inspect (shared browser)"},
            status_code=400,
        )

    from app.scraper.browser import BrowserManager
    from app.scraper.detail_scraper import _parse_seller, scrape_detail
    from app.scraper.pipeline import upsert_listing, update_vehicle_detail, mark_delisted

    browser = BrowserManager()
    browser.start()
    page = None
    try:
        page = browser.new_page()
        try:
            page.goto(url, wait_until="load", timeout=30_000)
        except Exception as e:
            return {"error": f"page load failed: {e}"}

        # Raw tel: hrefs — both site-wide (includes header support number)
        # and scoped to the seller phone list (the real phones).
        try:
            tel_hrefs_all = page.eval_on_selector_all(
                'a[href^="tel:"]',
                "els => els.map(e => e.getAttribute('href'))",
            )
        except Exception as e:
            tel_hrefs_all = [f"error: {e}"]
        try:
            tel_hrefs_scoped_before = page.eval_on_selector_all(
                '.product-phones__list a.product-phones__list-i[href^="tel:"]',
                "els => els.map(e => e.getAttribute('href'))",
            )
        except Exception as e:
            tel_hrefs_scoped_before = [f"error: {e}"]

        # Click the reveal button explicitly so the inspector shows the same
        # result the real scraper will get.
        tel_hrefs_scoped_after = tel_hrefs_scoped_before
        try:
            btn = page.query_selector(".product-phones__btn.js-phone-reveal-btn")
            if btn:
                btn.click()
                try:
                    page.wait_for_selector(
                        ".product-phones__list a.product-phones__list-i",
                        timeout=4_000,
                    )
                except Exception:
                    page.wait_for_timeout(500)
                tel_hrefs_scoped_after = page.eval_on_selector_all(
                    '.product-phones__list a.product-phones__list-i[href^="tel:"]',
                    "els => els.map(e => e.getAttribute('href'))",
                )
        except Exception as e:
            tel_hrefs_scoped_after = [f"click error: {e}"]

        # Seller container HTML (try several roots) — captured AFTER reveal click
        seller_html = None
        for sel in [
            ".product-owner",
            ".product-phones",
            ".product-owner__info",
        ]:
            try:
                el = page.query_selector(sel)
                if el:
                    seller_html = {
                        "selector": sel,
                        "html": el.evaluate("e => e.outerHTML")[:4000],
                    }
                    break
            except Exception:
                continue

        # Parse seller for the diagnostic output
        try:
            parsed_seller = _parse_seller(page)
        except Exception as e:
            parsed_seller = {"error": str(e)}

        # ── DB upsert ────────────────────────────────────────────────────
        # Run the full scrape_detail — reuses same page (wait_for_cloudflare
        # is idempotent, and phones__list is already populated above).
        detail = {}
        db_action = "skipped"
        db_error = None
        vehicle_id = None
        try:
            detail = scrape_detail(page, url)
        except Exception as e:
            db_error = f"scrape_detail failed: {e}"

        if detail and not db_error:
            try:
                with get_sync_conn() as conn, conn.cursor() as cur:
                    # Look up existing vehicle by turbo_id (extracted from URL)
                    import re
                    tm = re.search(r"/autos/(\d+)", url)
                    turbo_id = int(tm.group(1)) if tm else None
                    existing = None
                    if turbo_id:
                        cur.execute(
                            "SELECT id FROM vehicles WHERE turbo_id = %s",
                            (turbo_id,),
                        )
                        existing = cur.fetchone()

                    is_delisted = detail.get("delisted", False)
                    if is_delisted:
                        if existing:
                            vehicle_id = existing[0]
                            mark_delisted(conn, vehicle_id)
                            db_action = "marked_delisted"
                        else:
                            db_action = "skipped_delisted"
                    elif existing:
                        vehicle_id = existing[0]
                        update_vehicle_detail(conn, vehicle_id, detail)
                        conn.commit()
                        db_action = "updated"
                    else:
                        # Build minimal listing dict and insert
                        listing = _extract_listing_fields_from_detail(page, url)
                        if not listing:
                            db_error = "could not extract turbo_id from URL"
                        else:
                            result = upsert_listing(conn, listing)
                            # upsert_listing returns (vehicle_id, action, price_changed, needs_detail)
                            if isinstance(result, tuple) and result and result[0] is not None:
                                vehicle_id = result[0]
                                update_vehicle_detail(conn, vehicle_id, detail)
                                conn.commit()
                                db_action = "inserted"
                            else:
                                db_error = f"upsert_listing returned unexpected value: {result!r}"
            except Exception as e:
                db_error = f"db upsert failed: {e}"

        dt = detail.get("date_updated_turbo")
        return {
            "url": url,
            "is_delisted": detail.get("delisted", False),
            "db_action": db_action,
            "db_error": db_error,
            "vehicle_id": vehicle_id,
            "parsed_detail": {
                "labels": detail.get("labels", []),
                "features": detail.get("features", []),
                "fuel_type": detail.get("fuel_type"),
                "hp": detail.get("hp"),
                "vin": detail.get("vin"),
                "view_count_scraped": detail.get("view_count_scraped"),
                "date_updated_turbo": str(dt) if dt else None,
                "condition": detail.get("condition"),
                "market_for": detail.get("market_for"),
                "is_on_order": detail.get("is_on_order"),
                "price": detail.get("price"),
                "currency": detail.get("currency"),
            },
            "tel_hrefs_site_wide": tel_hrefs_all,
            "tel_hrefs_scoped_before_click": tel_hrefs_scoped_before,
            "tel_hrefs_scoped_after_click": tel_hrefs_scoped_after,
            "parsed_seller": parsed_seller,
            "seller_container": seller_html,
        }
    finally:
        if page is not None:
            try:
                browser.close_page(page)
            except Exception:
                pass
        browser.stop()


@app.post("/api/stop")
def api_stop():
    global _proc
    if _proc is None or _proc.poll() is not None:
        return {"running": False}
    _proc.terminate()
    try:
        _proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _proc.kill()
    return {"stopped": True, "exit_code": _proc.returncode}


if __name__ == "__main__":
    _auto_migrate()
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")
