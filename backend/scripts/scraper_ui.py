#!/usr/bin/env python3
"""
Local scraper UI — browser-based control panel for run_local.py.
Run from backend/:
    py -3.12 scripts/scraper_ui.py
Then open: http://localhost:8001

Features:
    - Start full / fresh / single-make / details-only / listings-only scans
    - Live stop button (SIGTERM, falls back to kill after 10s)
    - Tails scraper_local.log in real time
    - Shows checkpoint, DB stats, pending details count
"""
import json
import subprocess
import sys
from collections import deque
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent
LOG_FILE = BACKEND_DIR / "scraper_local.log"
CHECKPOINT_FILE = BACKEND_DIR / "scraper_checkpoint.txt"

sys.path.insert(0, str(BACKEND_DIR))

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

from app.scraper.pipeline import get_sync_conn

app = FastAPI()
_proc: subprocess.Popen | None = None


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
        <button id="btn-full">Full scan (resume)</button>
        <button id="btn-fresh" class="secondary">Fresh scan</button>
      </div>
      <div class="row">
        <label>Make:</label>
        <select id="make-select" style="min-width: 160px;"><option value="">(load…)</option></select>
        <button id="btn-make">Full scan make</button>
        <button id="btn-make-details" class="secondary">Details only (make)</button>
        <button id="btn-make-listings" class="secondary">Listings only (make)</button>
      </div>
      <div class="row">
        <label style="color:#8b94a3;">All makes:</label>
        <button id="btn-details" class="secondary">Details only</button>
        <button id="btn-listings" class="secondary">Listings only</button>
      </div>
      <div class="row" style="margin-top: 14px;">
        <button id="btn-reset-details" class="secondary" title="Clears raw_detail_json for selected make (or all if none selected) so Phase 2 will re-fetch them">Reset details (force re-scrape)</button>
        <button id="btn-reset-sellerless" class="secondary" title="Only clears vehicles where seller_id IS NULL (minimal re-work)">Reset only sellerless</button>
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
      <div class="stat"><span class="stat-label">Pending detail pages</span><span id="stat-pending" class="stat-value">—</span></div>
      <div class="stat"><span class="stat-label">Last DB update</span><span id="stat-last" class="stat-value">—</span></div>
      <div class="stat"><span class="stat-label">Process PID</span><span id="stat-pid" class="stat-value">—</span></div>
    </div>
  </div>

  <div class="card" style="margin-top: 16px;">
    <h2>Inspect detail page <span style="color:#8b94a3; font-weight:400; text-transform:none; letter-spacing:0; font-size:11px;">(scraper must be stopped)</span></h2>
    <div class="row">
      <input type="text" id="inspect-url" placeholder="https://turbo.az/autos/12345678-..." style="flex:1; min-width:280px;" />
      <button id="btn-inspect" class="secondary">Inspect</button>
    </div>
    <pre class="log" id="inspect-out" style="height: 260px;">Paste a turbo.az detail URL and click Inspect to see tel: links, parsed seller, and seller-container HTML.</pre>
  </div>

  <div class="card" style="margin-top: 16px;">
    <h2>Live log <span style="color:#8b94a3; font-weight:400; text-transform:none; letter-spacing:0; font-size:11px;">(scraper_local.log)</span>
      <label style="float:right;"><input type="checkbox" id="filter-input" checked> filter</label>
      <input type="text" id="filter-text" placeholder="filter (regex)" style="float:right; margin-right:8px; width:180px;" />
    </h2>
    <pre class="log" id="log">Waiting for output…</pre>
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

    ['btn-full','btn-fresh','btn-make','btn-details','btn-listings'].forEach(id => $(id).disabled = s.running);
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
    logEl.innerHTML = lines.map(colorize).join('');
    if (autoscroll) logEl.scrollTop = logEl.scrollHeight;
  } catch (e) {
    console.error(e);
  }
}

async function loadMakes() {
  try {
    const r = await api('/api/makes');
    const sel = $('make-select');
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

$('btn-full').onclick = () => start({ mode: 'full' });
$('btn-fresh').onclick = () => {
  if (confirm('Fresh scan ignores checkpoint and restarts from first make. Continue?')) {
    start({ mode: 'fresh' });
  }
};
$('btn-make').onclick = () => {
  const m = $('make-select').value;
  if (!m) { alert('Pick a make first'); return; }
  start({ mode: 'single', make: m });
};
$('btn-make-details').onclick = () => {
  const m = $('make-select').value;
  if (!m) { alert('Pick a make first'); return; }
  start({ mode: 'details', make: m });
};
$('btn-make-listings').onclick = () => {
  const m = $('make-select').value;
  if (!m) { alert('Pick a make first'); return; }
  start({ mode: 'listings', make: m });
};
$('btn-details').onclick = () => start({ mode: 'details' });
$('btn-listings').onclick = () => start({ mode: 'listings' });
$('btn-stop').onclick = async () => {
  if (!confirm('Stop scraper?')) return;
  await api('/api/stop', 'POST');
  refreshStatus();
};

$('btn-reset-details').onclick = async () => {
  const m = $('make-select').value;
  const label = m ? `make "${m}"` : 'ALL makes';
  if (!confirm(`Clear raw_detail_json for ${label}? Next "Details only" run will re-fetch every active vehicle.`)) return;
  const r = await api('/api/reset-details?' + new URLSearchParams(m ? { make: m } : {}), 'POST');
  alert(r.error ? 'Error: ' + r.error : `Reset ${r.updated} rows — now click "Details only"`);
  refreshStatus();
};
$('btn-reset-sellerless').onclick = async () => {
  const m = $('make-select').value;
  const label = m ? `make "${m}"` : 'ALL makes';
  if (!confirm(`Clear raw_detail_json for vehicles in ${label} where seller_id IS NULL?`)) return;
  const params = { sellerless: '1' };
  if (m) params.make = m;
  const r = await api('/api/reset-details?' + new URLSearchParams(params), 'POST');
  alert(r.error ? 'Error: ' + r.error : `Reset ${r.updated} sellerless rows — now click "Details only"`);
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
                  COUNT(*) FILTER (WHERE status = 'active' AND raw_detail_json IS NULL),
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
    mode: str = Query("full"),
    make: str | None = Query(None),
):
    """mode: full | fresh | single | details | listings"""
    global _proc
    if _proc is not None and _proc.poll() is None:
        return JSONResponse({"error": "scraper is already running"}, status_code=400)

    args = [sys.executable, "scripts/run_local.py"]
    if mode == "single":
        if not make:
            return JSONResponse({"error": "make is required"}, status_code=400)
        args += ["--make", make]
    elif mode == "details":
        args += ["--details-only", "--skip-lifecycle"]
        if make:
            args += ["--make", make]
    elif mode == "listings":
        args += ["--skip-details"]
        if make:
            args += ["--make", make]
    elif mode == "fresh":
        args += ["--fresh"]
    elif mode != "full":
        return JSONResponse({"error": f"unknown mode: {mode}"}, status_code=400)

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


@app.post("/api/reset-details")
def api_reset_details(
    make: str | None = Query(None),
    sellerless: bool = Query(False),
):
    """
    Clear raw_detail_json on active vehicles so Phase 2 will re-fetch them.
    Optional filters: make (case-insensitive), sellerless (seller_id IS NULL).
    """
    global _proc
    if _proc is not None and _proc.poll() is None:
        return JSONResponse(
            {"error": "stop the scraper first"}, status_code=400
        )

    sql = "UPDATE vehicles SET raw_detail_json = NULL WHERE status = 'active'"
    params: list = []
    if make:
        sql += " AND LOWER(make) = LOWER(%s)"
        params.append(make)
    if sellerless:
        sql += " AND seller_id IS NULL"
    try:
        with get_sync_conn() as conn, conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            conn.commit()
            return {"updated": cur.rowcount}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/inspect")
def api_inspect(url: str):
    """
    Load a detail page in a fresh browser page and return:
      - parsed seller dict (what update_vehicle_detail would store)
      - all tel: links found
      - HTML snippet of the seller-area container
    Useful for diagnosing why seller/phone fields come back empty.
    Requires scraper NOT to be running (shares the CDP browser).
    """
    global _proc
    if _proc is not None and _proc.poll() is None:
        return JSONResponse(
            {"error": "stop the scraper before using inspect (shared browser)"},
            status_code=400,
        )

    from app.scraper.browser import BrowserManager
    from app.scraper.detail_scraper import scrape_detail, _parse_seller

    browser = BrowserManager()
    browser.start()
    try:
        page = browser.new_page()
        try:
            page.goto(url, wait_until="load", timeout=30_000)
        except Exception as e:
            return {"error": f"page load failed: {e}"}

        # Raw tel: hrefs
        try:
            tel_hrefs = page.eval_on_selector_all(
                'a[href^="tel:"]',
                "els => els.map(e => e.getAttribute('href'))",
            )
        except Exception as e:
            tel_hrefs = [f"error: {e}"]

        # Seller container HTML (try several roots)
        seller_html = None
        for sel in [
            ".product-owner",
            ".product-owner__info",
            ".shop-owner",
            ".seller-info",
            ".product-phones",
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

        # Full parsed detail
        try:
            full = scrape_detail(page, url)
        except Exception as e:
            full = {"error": str(e)}

        try:
            parsed_seller = _parse_seller(page)
        except Exception as e:
            parsed_seller = {"error": str(e)}

        browser.close_page(page)
        return {
            "url": url,
            "tel_hrefs": tel_hrefs,
            "parsed_seller": parsed_seller,
            "parsed_city": full.get("city") if isinstance(full, dict) else None,
            "seller_container": seller_html,
        }
    finally:
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
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")
