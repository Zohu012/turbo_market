"""
Listing page scraper — ported from turbo_sync/scraper.py with DB backend.

Parses listing cards from turbo.az/autos pages (20 cards per page).
Returns structured dicts ready for DB upsert.
"""
import logging
import re
import time
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from app.config import settings

log = logging.getLogger(__name__)

BASE_URL = "https://turbo.az"
AUTOS_URL = f"{BASE_URL}/autos"

MULTI_WORD_MAKES = {
    "Land Rover", "Aston Martin", "Alfa Romeo", "Great Wall",
    "Rolls Royce", "Rolls-Royce", "Mercedes Benz",
}


# ── Cloudflare ──────────────────────────────────────────────────────────────────

def wait_for_cloudflare(page: Page, timeout_ms: int = 60_000):
    start = time.time()
    while True:
        try:
            if "just a moment" not in page.title().lower():
                return
        except Exception:
            try:
                page.wait_for_load_state("load", timeout=15_000)
            except Exception:
                pass
            return
        elapsed = (time.time() - start) * 1000
        if elapsed > timeout_ms:
            log.warning("Cloudflare challenge did not clear within timeout.")
            return
        log.info(f"Waiting for Cloudflare... ({int(elapsed / 1000)}s)")
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


def to_price_azn(price: Optional[int], currency: Optional[str]) -> Optional[float]:
    if price is None:
        return None
    if currency == "AZN":
        return float(price)
    if currency == "USD":
        return round(float(price) * settings.azn_per_usd, 2)
    return None


# ── Page parsing ────────────────────────────────────────────────────────────────

def parse_listing_page(page: Page) -> list[dict]:
    cards = page.eval_on_selector_all(
        "div.products-i",
        """els => els.map(el => {
            const link  = el.querySelector('a.products-i__link');
            const name  = el.querySelector('.products-i__name');
            const attrs = el.querySelector('.products-i__attributes');
            const price = el.querySelector('.products-i__price');
            return {
                href:  link  ? link.getAttribute('href')  : '',
                name:  name  ? name.textContent.trim()    : '',
                attrs: attrs ? attrs.textContent.trim()   : '',
                price: price ? price.textContent.trim()   : '',
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
            "engine": engine,
            "url": url,
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


def scrape_make_pages(
    page: Page,
    make: dict,
    start_page: int = 1,
    progress_callback=None,
) -> list[dict]:
    """
    Scrape all listing pages for a single make.
    Returns flat list of vehicle dicts from listing cards.
    Calls progress_callback(page_num, total_pages, new_on_page) if provided.
    """
    make_url = f"{AUTOS_URL}?q[make][]={make['id']}"
    url = make_url if start_page == 1 else f"{make_url}&page={start_page}"
    page.goto(url, wait_until="load", timeout=30_000)
    wait_for_cloudflare(page)

    total_pages = get_total_pages(page)
    if settings.max_pages > 0:
        total_pages = min(total_pages, settings.max_pages)

    all_vehicles = []
    for page_num in range(start_page, total_pages + 1):
        if page_num > start_page:
            page.goto(f"{make_url}&page={page_num}", wait_until="load", timeout=30_000)
            wait_for_cloudflare(page)

        vehicles = parse_listing_page(page)
        if not vehicles:
            log.info(f"  {make['name']} p{page_num}: no cards, stopping.")
            break

        all_vehicles.extend(vehicles)
        if progress_callback:
            progress_callback(page_num, total_pages, len(vehicles))

        page.wait_for_timeout(int(settings.delay_seconds * 1000))

    return all_vehicles
