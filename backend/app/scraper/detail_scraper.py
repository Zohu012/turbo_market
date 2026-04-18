"""
Detail page scraper — fetches /autos/{turbo_id} and extracts full vehicle data.

Collects: images, all spec table fields, description, seller info, view count.
"""
import json
import logging
import re
from typing import Optional

from playwright.sync_api import Page

from app.scraper.listing_scraper import wait_for_cloudflare, to_price_azn, parse_price

log = logging.getLogger(__name__)


def normalize_phone(raw: str) -> str:
    """Strip all non-digit characters, remove leading country code 994."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("994") and len(digits) > 9:
        digits = digits[3:]
    return digits


def scrape_detail(page: Page, url: str) -> dict:
    """
    Navigate to a vehicle detail page and return a dict with all available fields.
    Returns empty dict on failure (caller decides how to handle).
    """
    try:
        page.goto(url, wait_until="load", timeout=30_000)
        wait_for_cloudflare(page)
    except Exception as e:
        log.warning(f"Failed to load {url}: {e}")
        return {}

    data: dict = {}

    # ── Images ──────────────────────────────────────────────────────────────────
    try:
        images = page.eval_on_selector_all(
            ".product-photos__list img, .product-photos img, .photo-gallery img",
            "els => els.map(e => e.getAttribute('src') || e.getAttribute('data-src') || '').filter(Boolean)"
        )
        # Deduplicate while preserving order
        seen = set()
        unique_images = []
        for img in images:
            if img not in seen and "turbo.az" in img or img.startswith("https://"):
                seen.add(img)
                unique_images.append(img)
        data["images"] = unique_images
    except Exception as e:
        log.debug(f"Images parse error for {url}: {e}")
        data["images"] = []

    # ── Spec table ──────────────────────────────────────────────────────────────
    try:
        specs_raw = page.eval_on_selector_all(
            ".product-properties__i, .product-properties li",
            """els => els.map(el => {
                const label = el.querySelector('.product-properties__i-name, label, .key');
                const value = el.querySelector('.product-properties__i-value, span, .value');
                return {
                    key: label ? label.textContent.trim() : '',
                    val: value ? value.textContent.trim() : ''
                };
            })"""
        )
        specs = {s["key"].lower(): s["val"] for s in specs_raw if s["key"] and s["val"]}
        data["specs"] = specs

        # Map known spec keys
        data["color"] = _find(specs, ["rəng", "color", "цвет"])
        data["body_type"] = _find(specs, ["ban növü", "body type", "кузов", "növü"])
        data["transmission"] = _find(specs, ["sürətlər qutusu", "transmission", "коробка передач", "sürət"])
        data["fuel_type"] = _find(specs, ["yanacaq", "fuel type", "двигатель", "mühərrik növü"])
        data["drive_type"] = _find(specs, ["ötürücü", "drive", "привод"])
        data["doors"] = _parse_int(_find(specs, ["qapı sayı", "doors", "двери"]))
        data["vin"] = _find(specs, ["vin", "vin-kod"])
    except Exception as e:
        log.debug(f"Specs parse error for {url}: {e}")
        data["specs"] = {}

    # ── Description ─────────────────────────────────────────────────────────────
    try:
        desc_el = page.query_selector(".product-description__content, .product-text, .description")
        if desc_el:
            data["description"] = desc_el.inner_text().strip() or None
    except Exception:
        pass

    # ── View count ──────────────────────────────────────────────────────────────
    try:
        view_el = page.query_selector(".product-statistics__i-count, .view-count")
        if view_el:
            data["view_count"] = _parse_int(view_el.inner_text())
    except Exception:
        pass

    # ── Seller ──────────────────────────────────────────────────────────────────
    try:
        seller_data = _parse_seller(page)
        data["seller"] = seller_data
        data["city"] = seller_data.get("city")
    except Exception as e:
        log.debug(f"Seller parse error for {url}: {e}")
        data["seller"] = {}

    # ── Store raw dump ───────────────────────────────────────────────────────────
    data["raw_detail_json"] = {
        "specs": data.get("specs", {}),
        "images": data.get("images", []),
    }

    return data


def _parse_seller(page: Page) -> dict:
    """
    Extract seller info from a turbo.az detail page.

    DOM reference (verified 2026-04):
      .product-owner
        .product-owner__info
          .product-owner__info-name      → name
          .product-owner__info-region    → city
          .product-owner__info-regdate   → "Satıcı MM.YYYY tarixindən ..." (join date)
      .product-phones.js-phone-reveal
        .product-phones__btn.js-phone-reveal-btn   → click to reveal
        .product-phones__list
          a.product-phones__list-i[href^="tel:"]   → one <a> per phone number

      #chat-write-link
        data-user      → numeric turbo.az user id (stable, unique per seller)
        data-receiver  → JSON with {id, name, phones: [...]} (phones available
                         WITHOUT clicking reveal — use as primary source)
    """
    seller: dict = {}

    # ── turbo_seller_id + name from chat-link metadata (no click needed) ────
    turbo_user_id = None
    dr_phones: list[str] = []
    try:
        chat_el = page.query_selector("#chat-write-link")
        if chat_el:
            du = chat_el.get_attribute("data-user")
            if du and du.isdigit():
                turbo_user_id = du
            dr = chat_el.get_attribute("data-receiver")
            if dr:
                try:
                    payload = json.loads(dr)
                    if isinstance(payload, dict):
                        if not turbo_user_id and payload.get("id"):
                            turbo_user_id = str(payload["id"])
                        if isinstance(payload.get("phones"), list):
                            dr_phones = [p for p in payload["phones"] if p]
                        if not seller.get("name") and payload.get("name"):
                            seller["name"] = payload["name"]
                except Exception:
                    pass
    except Exception:
        pass

    if turbo_user_id:
        seller["turbo_seller_id"] = turbo_user_id

    # ── Phones: MUST come from .product-phones__list (never page-wide, to
    #    avoid picking up the site-wide support number in the header). The
    #    list is populated only after clicking the reveal button on unauthed
    #    sessions. ───────────────────────────────────────────────────────────
    PHONE_SELECTOR = ".product-phones__list a.product-phones__list-i"

    def _read_list_phones() -> list[str]:
        try:
            return page.eval_on_selector_all(
                PHONE_SELECTOR,
                "els => Array.from(new Set(els.map(e => (e.getAttribute('href') || '').replace(/^tel:\\s*/i, '').trim()).filter(Boolean)))",
            )
        except Exception:
            return []

    phones_raw = _read_list_phones()

    if not phones_raw:
        # Click the reveal button; then wait for the list to render
        try:
            btn = page.query_selector(
                ".product-phones__btn.js-phone-reveal-btn, "
                ".product-phones .js-phone-reveal-btn"
            )
            if btn:
                try:
                    btn.scroll_into_view_if_needed(timeout=1_500)
                except Exception:
                    pass
                btn.click()
                try:
                    page.wait_for_selector(PHONE_SELECTOR, timeout=4_000)
                except Exception:
                    page.wait_for_timeout(500)
                phones_raw = _read_list_phones()
        except Exception:
            pass

    # Fallback: data-receiver (only when logged in — usually empty for unauthed)
    if not phones_raw and dr_phones:
        phones_raw = dr_phones

    seller["phones"] = phones_raw
    seller["phones_normalized"] = [
        p for p in (normalize_phone(x) for x in phones_raw) if p
    ]

    # ── Name / city / regdate from product-owner block ──────────────────────
    for sel, key in [
        (".product-owner__info-name", "name"),
        (".product-owner__info-region", "city"),
        (".product-owner__info-regdate", "regdate"),
    ]:
        if seller.get(key):
            continue
        try:
            el = page.query_selector(sel)
            if el:
                txt = (el.inner_text() or "").strip()
                if txt:
                    seller[key] = txt
        except Exception:
            continue

    # ── Profile URL (shops link, if present) ────────────────────────────────
    profile_url = None
    try:
        el = page.query_selector(
            '.product-owner a[href*="/shops/"], a.product-owner__info-title'
        )
        if el:
            href = el.get_attribute("href")
            if href:
                profile_url = (
                    f"https://turbo.az{href}" if href.startswith("/") else href
                )
    except Exception:
        pass
    if profile_url:
        seller["profile_url"] = profile_url

    # ── Dealer detection ────────────────────────────────────────────────────
    is_dealer = False
    if profile_url and "/shops/" in profile_url:
        is_dealer = True
    else:
        try:
            if page.query_selector(".product-owner__logo img, .shop-owner, .shop-badge"):
                is_dealer = True
        except Exception:
            pass
    seller["seller_type"] = "dealer" if is_dealer else "private"

    return seller


def _find(specs: dict, keys: list[str]) -> Optional[str]:
    for k in keys:
        val = specs.get(k)
        if val:
            return val
    # Partial match fallback
    for key, val in specs.items():
        for k in keys:
            if k in key:
                return val
    return None


def _parse_int(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None
