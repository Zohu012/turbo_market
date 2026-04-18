"""
Detail page scraper — fetches /autos/{turbo_id} and extracts full vehicle data.

Collects: images, all spec table fields, description, seller info, view count.
"""
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
    seller = {}
    try:
        name_el = page.query_selector(".seller-name, .product-owner__name, .shop-name")
        if name_el:
            seller["name"] = name_el.inner_text().strip()
    except Exception:
        pass

    try:
        # Detect dealer badge
        badge = page.query_selector(".seller-type-badge, .shop-badge, .dealer-badge")
        if badge:
            seller["seller_type"] = "dealer"
        else:
            seller["seller_type"] = "private"
    except Exception:
        seller["seller_type"] = "private"

    try:
        city_el = page.query_selector(".product-owner__city, .seller-city, .city")
        if city_el:
            seller["city"] = city_el.inner_text().strip()
    except Exception:
        pass

    try:
        phone_els = page.query_selector_all(".product-owner__phone, .seller-phone, .phone-number")
        phones_raw = [el.inner_text().strip() for el in phone_els if el.inner_text().strip()]
        # Also try to reveal hidden phones via button click
        if not phones_raw:
            show_btn = page.query_selector("button.show-phones, .show-number-btn, .call-seller")
            if show_btn:
                show_btn.click()
                page.wait_for_timeout(1_000)
                phone_els = page.query_selector_all(".product-owner__phone, .seller-phone, .phone-number")
                phones_raw = [el.inner_text().strip() for el in phone_els if el.inner_text().strip()]
        seller["phones"] = phones_raw
        seller["phones_normalized"] = [normalize_phone(p) for p in phones_raw]
    except Exception:
        seller["phones"] = []
        seller["phones_normalized"] = []

    try:
        profile_el = page.query_selector("a.seller-profile-link, a.shop-link")
        if profile_el:
            href = profile_el.get_attribute("href")
            seller["profile_url"] = f"https://turbo.az{href}" if href and href.startswith("/") else href
    except Exception:
        pass

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
