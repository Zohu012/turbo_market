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
    """
    Extract seller info from a turbo.az detail page.

    Strategy:
      - Phones: collect all `a[href^="tel:"]` anywhere on the page. This is the
        most reliable signal — phones are encoded into the tel: link value even
        when the visible text is styled/split. Falls back to a reveal-button
        click if none are found on first pass.
      - Name/city/profile: try a few known class patterns, then fall back to
        heuristics.
      - Dealer vs private: if any tel: link lives inside a shop/dealer container
        OR the profile link points to /shops/, mark as 'dealer'; else private.
    """
    seller: dict = {}

    # ── Phones (via tel: links — most reliable) ─────────────────────────────
    phones_raw: list[str] = []
    try:
        phones_raw = page.eval_on_selector_all(
            'a[href^="tel:"]',
            "els => Array.from(new Set(els.map(e => (e.getAttribute('href') || '').replace(/^tel:/, '').trim()).filter(Boolean)))",
        )
    except Exception:
        pass

    # Fallback: try clicking a reveal button, then re-query
    if not phones_raw:
        try:
            reveal = page.query_selector(
                'button:has-text("Nömrə"), button:has-text("Göstər"), button.show-phones, '
                '.phone-reveal, .show-number-btn, .product-phones__reveal'
            )
            if reveal:
                reveal.click()
                page.wait_for_timeout(1_000)
                phones_raw = page.eval_on_selector_all(
                    'a[href^="tel:"]',
                    "els => Array.from(new Set(els.map(e => (e.getAttribute('href') || '').replace(/^tel:/, '').trim()).filter(Boolean)))",
                )
        except Exception:
            pass

    # Last resort: extract +994… / 0XX patterns from text in seller container
    if not phones_raw:
        try:
            container_text = page.eval_on_selector(
                ".product-owner, .product-owner__info, .shop-owner, .seller-info",
                "el => el.innerText",
            )
            phones_raw = re.findall(
                r"(?:\+?994|0)\s*\(?\d{2}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}",
                container_text or "",
            )
        except Exception:
            pass

    seller["phones"] = phones_raw
    seller["phones_normalized"] = [normalize_phone(p) for p in phones_raw]

    # ── Name ────────────────────────────────────────────────────────────────
    for sel in [
        ".product-owner__info-title",
        ".shop-owner__name",
        ".seller-name",
        ".product-owner__name",
        ".shop-name",
        ".product-owner a",  # profile link text
    ]:
        try:
            el = page.query_selector(sel)
            if el:
                txt = (el.inner_text() or "").strip()
                if txt:
                    seller["name"] = txt
                    break
        except Exception:
            continue

    # ── Profile URL (also used to detect dealer) ────────────────────────────
    profile_url = None
    for sel in [
        'a.product-owner__info-title',
        'a.shop-owner__link',
        '.product-owner a[href*="/shops/"]',
        '.product-owner a[href*="/autos?"]',
        'a.seller-profile-link',
        'a.shop-link',
    ]:
        try:
            el = page.query_selector(sel)
            if el:
                href = el.get_attribute("href")
                if href:
                    profile_url = (
                        f"https://turbo.az{href}" if href.startswith("/") else href
                    )
                    break
        except Exception:
            continue
    if profile_url:
        seller["profile_url"] = profile_url

    # ── Dealer detection ────────────────────────────────────────────────────
    is_dealer = False
    if profile_url and "/shops/" in profile_url:
        is_dealer = True
    else:
        try:
            if page.query_selector(
                ".shop-badge, .dealer-badge, .seller-type-badge, "
                ".product-owner__shop, .shop-owner"
            ):
                is_dealer = True
        except Exception:
            pass
    seller["seller_type"] = "dealer" if is_dealer else "private"

    # ── City / region ───────────────────────────────────────────────────────
    for sel in [
        ".product-owner__region",
        ".product-owner__city",
        ".seller-city",
        ".product-owner__info-region",
    ]:
        try:
            el = page.query_selector(sel)
            if el:
                txt = (el.inner_text() or "").strip()
                if txt:
                    seller["city"] = txt
                    break
        except Exception:
            continue

    # Fallback: city is often in the first specs row ("Şəhər"), but that's
    # already captured via the spec table on the caller side.

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
