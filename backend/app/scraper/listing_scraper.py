"""
Listing page scraper — ported from turbo_sync/scraper.py with DB backend.

Parses listing cards from turbo.az/autos pages (20 cards per page).
Returns structured dicts ready for DB upsert.
"""
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from app.config import settings

# Baku is UTC+4 year-round (no DST). turbo.az timestamps are local Baku time.
BAKU_TZ = timezone(timedelta(hours=4))

log = logging.getLogger(__name__)

BASE_URL = "https://turbo.az"
AUTOS_URL = f"{BASE_URL}/autos"

MULTI_WORD_MAKES = {
    "Land Rover", "Aston Martin", "Alfa Romeo", "Great Wall",
    "Rolls Royce", "Rolls-Royce", "Mercedes Benz",
}


# ── Cloudflare ──────────────────────────────────────────────────────────────────

def wait_for_cloudflare(page: Page, timeout_ms: int = 60_000, manual_after_ms: int = 30_000):
    """
    Wait for Cloudflare challenge to clear.

    After `manual_after_ms` (30s), assume the challenge is the interactive
    checkbox variant that needs a human click — bring the tab to front in
    Chrome, log loudly, and keep waiting indefinitely (no hard timeout)
    until the title clears. This is the recovery path for CDP mode.
    """
    start = time.time()
    brought_to_front = False
    loud_logged = False
    while True:
        try:
            if "just a moment" not in page.title().lower():
                if brought_to_front:
                    log.info("Cloudflare cleared — resuming.")
                return
        except Exception:
            try:
                page.wait_for_load_state("load", timeout=15_000)
            except Exception:
                pass
            return
        elapsed_ms = (time.time() - start) * 1000

        # After `manual_after_ms`: switch into manual-assist mode
        if elapsed_ms > manual_after_ms and not brought_to_front:
            try:
                page.bring_to_front()
            except Exception:
                pass
            brought_to_front = True

        if brought_to_front:
            if not loud_logged or int(elapsed_ms / 1000) % 15 == 0:
                log.warning(
                    "MANUAL CLICK NEEDED IN CHROME — click the Cloudflare "
                    f"checkbox on the focused tab ({page.url})"
                )
                loud_logged = True
            page.wait_for_timeout(3_000)
            continue

        # Pre-manual phase — still within the automatic wait window
        if elapsed_ms > timeout_ms and not brought_to_front:
            # Unreachable in practice since manual_after_ms < timeout_ms,
            # but keep for safety.
            log.warning("Cloudflare challenge did not clear within timeout.")
            return
        log.info(f"Waiting for Cloudflare... ({int(elapsed_ms / 1000)}s)")
        page.wait_for_timeout(2_000)


# ── Parsing helpers ─────────────────────────────────────────────────────────────

def extract_turbo_id(href: str) -> Optional[int]:
    m = re.search(r"/autos/(\d+)", href)
    return int(m.group(1)) if m else None


def split_make_model(name: str) -> tuple[str, str]:
    for make in MULTI_WORD_MAKES:
        if name.startswith(make + " "):
            return make, name[len(make):].strip()
    parts = name.split(" ", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def parse_price(text: str) -> tuple[Optional[int], Optional[str]]:
    azn = re.search(r"([\d\s]+)₼", text)
    if azn:
        return int(re.sub(r"\s", "", azn.group(1))), "AZN"
    usd = re.search(r"([\d\s]+)\$", text)
    if usd:
        return int(re.sub(r"\s", "", usd.group(1))), "USD"
    return None, None


def parse_odometer(text: str) -> tuple[Optional[int], Optional[str]]:
    m = re.search(r"([\d\s]+)(km|mi)", text, re.IGNORECASE)
    if m:
        return int(re.sub(r"\s", "", m.group(1))), m.group(2).lower()
    return None, None


def parse_engine_cc(text: Optional[str]) -> Optional[int]:
    """
    Extract engine displacement in cubic centimeters.
      "3.4 L / 409 a.g. / Hibrid" -> 3400
      "1.5 L"                     -> 1500
      "2500 sm³"                  -> 2500
      "Elektro"                   -> None
    """
    if not text:
        return None
    # Liters: "3.4 L" -> 3400. \bL\b avoids matching "LPG" etc.
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*L\b", text, re.IGNORECASE)
    if m:
        return int(round(float(m.group(1).replace(",", ".")) * 1000))
    # Already cc: "2500 sm³" / "2500 cc" / "2500 см³"
    m = re.search(r"(\d{3,5})\s*(?:cc|sm[³3]|см[³3])", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def to_price_azn(price: Optional[int], currency: Optional[str]) -> Optional[float]:
    if price is None:
        return None
    if currency == "AZN":
        return float(price)
    if currency == "USD":
        return round(float(price) * settings.azn_per_usd, 2)
    return None


# Matches "Bakı, 15.04.2026 10:53" (city is everything before the first comma;
# we only care about the date+time). Date-only ("15.04.2026") also accepted.
_LISTING_DT_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2}))?"
)
# Matches relative Azerbaijani times: "bugün 22:10" or "dünən 21:04"
_LISTING_RELATIVE_RE = re.compile(
    r"\b(bugün|dünən)\s+(\d{1,2}):(\d{2})\b"
)


def parse_listing_datetime(raw: Optional[str]) -> Optional[datetime]:
    """
    Parse a .products-i__datetime string like "Bakı, 15.04.2026 10:53",
    "Bakı, bugün 22:10", or "Bakı, dünən 21:04".
    Returns a timezone-aware UTC datetime, or None if the pattern doesn't match.
    """
    if not raw:
        return None
    # Everything after the first comma is the timestamp portion.
    if "," in raw:
        raw = raw.split(",", 1)[1]
    # Try relative terms first (bugün = today, dünən = yesterday in Baku time).
    rel = _LISTING_RELATIVE_RE.search(raw)
    if rel:
        word, hour, minute = rel.group(1), int(rel.group(2)), int(rel.group(3))
        today_baku = datetime.now(BAKU_TZ).date()
        date = today_baku if word == "bugün" else today_baku - timedelta(days=1)
        try:
            local = datetime(date.year, date.month, date.day, hour, minute, tzinfo=BAKU_TZ)
        except ValueError:
            return None
        return local.astimezone(timezone.utc)
    m = _LISTING_DT_RE.search(raw)
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hour = int(m.group(4)) if m.group(4) else 0
    minute = int(m.group(5)) if m.group(5) else 0
    try:
        local = datetime(year, month, day, hour, minute, tzinfo=BAKU_TZ)
    except ValueError:
        return None
    return local.astimezone(timezone.utc)


# ── Page parsing ────────────────────────────────────────────────────────────────

def parse_listing_page(page: Page) -> list[dict]:
    cards = page.eval_on_selector_all(
        "div.products-i",
        """els => els.map(el => {
            const link  = el.querySelector('a.products-i__link');
            const name  = el.querySelector('.products-i__name');
            const attrs = el.querySelector('.products-i__attributes');
            const price = el.querySelector('.products-i__price');
            const dt    = el.querySelector('.products-i__datetime');
            return {
                href:  link  ? link.getAttribute('href')  : '',
                name:  name  ? name.textContent.trim()    : '',
                attrs: attrs ? attrs.textContent.trim()   : '',
                price: price ? price.textContent.trim()   : '',
                dt:    dt    ? dt.textContent.trim()      : '',
            };
        })"""
    )

    results = []
    for c in cards:
        turbo_id = extract_turbo_id(c["href"])
        if not turbo_id:
            continue
        url = BASE_URL + c["href"] if c["href"].startswith("/") else c["href"]
        make, model = split_make_model(c["name"])
        price_val, currency = parse_price(c["price"])
        parts = [p.strip() for p in c["attrs"].split(",")]
        year_str = parts[0] if parts else ""
        year = int(year_str) if year_str.isdigit() else None
        engine, odo_val, odo_type = None, None, None
        for part in parts[1:]:
            val, unit = parse_odometer(part)
            if unit:
                odo_val, odo_type = val, unit
            elif not engine:
                engine = part or None
        results.append({
            "turbo_id": turbo_id,
            "make": make,
            "model": model,
            "year": year,
            "price": price_val,
            "currency": currency,
            "price_azn": to_price_azn(price_val, currency),
            "odometer": odo_val,
            "odometer_type": odo_type,
            "engine": parse_engine_cc(engine),
            "url": url,
            "date_updated_turbo": parse_listing_datetime(c["dt"]),
        })
    return results


def get_total_pages(page: Page) -> int:
    try:
        text = page.locator(".products-title-amount").first.inner_text()
        total = int(re.sub(r"\D", "", text))
        return min((total + 19) // 20, 500)
    except Exception:
        return 1


def get_all_makes(page: Page) -> list[dict]:
    """Return list of {id, name} dicts from the filter dropdown."""
    page.goto(AUTOS_URL, wait_until="load", timeout=30_000)
    wait_for_cloudflare(page)
    return page.eval_on_selector_all(
        "select[name='q[make][]'] option",
        "els => els.filter(e => e.value).map(e => ({id: e.value, name: e.textContent.trim()}))"
    )


def _goto_with_retry(page: Page, url: str, attempts: int = 2) -> bool:
    """Navigate with one retry on timeout. Returns True on success."""
    for i in range(attempts):
        try:
            page.goto(url, wait_until="load", timeout=30_000)
            wait_for_cloudflare(page)
            return True
        except Exception as e:
            if i == attempts - 1:
                log.warning(f"  goto failed after {attempts} attempts: {url} — {e}")
                return False
            log.info(f"  goto retry ({i + 1}/{attempts - 1}): {url}")
            page.wait_for_timeout(2_000)
    return False


def scrape_make_pages(
    page: Page,
    make: dict,
    start_page: int = 1,
    progress_callback=None,
    on_page_complete=None,
) -> tuple[list[dict], bool]:
    """
    Scrape all listing pages for a single make.

    Returns ``(vehicles, stopped_early)`` where ``stopped_early`` is True when
    the run ended on a page-load failure rather than a clean "no more pages".
    Callers must NOT mark the make as fully-done when ``stopped_early`` is True
    — the per-page sidecar already holds the last successfully-committed page,
    so the next run will resume from there automatically.

    Calls progress_callback(page_num, total_pages, new_on_page) if provided.
    Calls on_page_complete(vehicles_on_page, page_num) after each page is parsed.
    """
    make_url = f"{AUTOS_URL}?q[make][]={make['id']}"
    url = make_url if start_page == 1 else f"{make_url}&page={start_page}"
    if not _goto_with_retry(page, url):
        return [], True

    total_pages = get_total_pages(page)
    if settings.max_pages > 0:
        total_pages = min(total_pages, settings.max_pages)

    all_vehicles = []
    stopped_early = False
    for page_num in range(start_page, total_pages + 1):
        if page_num > start_page:
            if not _goto_with_retry(page, f"{make_url}&page={page_num}"):
                log.warning(f"  {make['name']} p{page_num}: goto failed, stopping make.")
                stopped_early = True
                break

        vehicles = parse_listing_page(page)
        if not vehicles:
            log.info(f"  {make['name']} p{page_num}: no cards, stopping.")
            break

        all_vehicles.extend(vehicles)

        # Commit this page's results immediately so a later timeout can't
        # discard earlier pages (Chevrolet has 85+ pages — losing them all
        # because page 85 timed out was the old bug).
        if on_page_complete:
            try:
                on_page_complete(vehicles, page_num)
            except Exception as e:
                log.error(f"  {make['name']} p{page_num}: on_page_complete raised: {e}")

        if progress_callback:
            progress_callback(page_num, total_pages, len(vehicles))

        page.wait_for_timeout(int(settings.delay_seconds * 1000))

    return all_vehicles, stopped_early
