"""
Detail page scraper — fetches /autos/{turbo_id} and extracts full vehicle data.

Collects: images, all spec table fields, description, seller info, view count,
features, labels, on-order pricing, delisted status.
"""
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from playwright.sync_api import Page

from app.scraper.listing_scraper import (
    BAKU_TZ,
    wait_for_cloudflare,
    to_price_azn,
    parse_price,
    parse_engine_cc,
)

log = logging.getLogger(__name__)


def normalize_phone(raw: str) -> str:
    """Strip all non-digit characters, remove leading country code 994."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("994") and len(digits) > 9:
        digits = digits[3:]
    return digits


def parse_engine(raw: Optional[str]) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """
    Parse the engine property value. Examples:
      "1.5 L / 185 a.g. / Benzin"     -> ("1.5 L", 185, "Benzin")
      "690 a.g. / Elektro"            -> (None,    690, "Elektro")
      "Benzin"                         -> (None,    None, "Benzin")
    Returns (engine_volume, hp, fuel_type).
    """
    if not raw:
        return None, None, None

    parts = [p.strip() for p in raw.split("/") if p.strip()]
    hp: Optional[int] = None
    fuel_type: Optional[str] = None
    engine_volume: Optional[str] = None

    # hp = any segment matching "<digits> a.g." (Azerbaijani for "h.p.")
    for p in parts:
        m = re.search(r"(\d+)\s*a\.g\.?", p, re.IGNORECASE)
        if m and hp is None:
            hp = int(m.group(1))

    # Anything without digits and without "L" is the fuel type — typically
    # the last segment (Benzin/Dizel/Elektro/Hibrid/...).
    for p in reversed(parts):
        if not re.search(r"\d", p) and not re.search(r"\bL\b", p):
            fuel_type = p
            break
    if fuel_type is None:
        # fall back to the last segment verbatim
        fuel_type = parts[-1] if parts else None

    # Engine volume = first segment containing "L" (e.g., "1.5 L").
    for p in parts:
        if re.search(r"\bL\b", p):
            engine_volume = p
            break

    return engine_volume, hp, fuel_type


def parse_seller_location(raw: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Split a turbo.az shop location string into (city, address).

    Rules (in order):
      - "Bakı ş., Nərimanov r., küç., 16" → city="Bakı", address="Nərimanov r., küç., 16"
      - "Nizami r., Babək pr., 74a"       → city="Bakı",  address=whole string
      - "Bakı" or any other text          → city=whole,   address=None
    """
    if not raw:
        return None, None
    raw = raw.strip()
    m = re.match(r"^(.+?)\s+ş\.,\s*(.+)$", raw)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    if "r.," in raw:
        return "Bakı", raw
    return raw, None


_DATE_DDMMYYYY = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def parse_turbo_date(raw: Optional[str]) -> Optional[datetime]:
    """Parse 'DD.MM.YYYY' (no time) as UTC midnight Baku time → UTC."""
    if not raw:
        return None
    m = _DATE_DDMMYYYY.search(raw)
    if not m:
        return None
    try:
        local = datetime(
            int(m.group(3)), int(m.group(2)), int(m.group(1)),
            tzinfo=BAKU_TZ,
        )
    except ValueError:
        return None
    return local.astimezone(timezone.utc)


_REGDATE_RE = re.compile(r"(\d{2})\.(\d{4})")


def parse_regdate(raw: Optional[str]) -> Optional[date]:
    """Parse seller's 'Satıcı MM.YYYY tarixindən ...' → date(YYYY, MM, 1)."""
    if not raw:
        return None
    m = _REGDATE_RE.search(raw)
    if not m:
        return None
    try:
        return date(int(m.group(2)), int(m.group(1)), 1)
    except ValueError:
        return None


def _detect_delisted(page: Page) -> bool:
    """Three overlapping delisted markers — any one is sufficient."""
    try:
        if page.query_selector(".status-message--expired"):
            return True
    except Exception:
        pass
    try:
        overlay = page.query_selector(".product-photos__slider-top-i_overlay")
        if overlay:
            text = (overlay.inner_text() or "").strip().lower()
            if "satışdan çıxarılıb" in text:
                return True
    except Exception:
        pass
    try:
        if not page.query_selector(".product-sidebar__box"):
            return True
    except Exception:
        pass
    return False


def scrape_detail(page: Page, url: str) -> dict:
    """
    Navigate to a vehicle detail page and return a dict with all available fields.
    Returns empty dict on failure (caller decides how to handle).

    If the listing is delisted, returns {"delisted": True} — callers should
    mark the vehicle inactive WITHOUT overwriting its existing data.
    """
    # One retry on timeout. With parallel workers (8 concurrent contexts),
    # fail-fast is cheaper than a long blocking wait — the row gets re-queued
    # to scraper_failed_<key>.txt and retried on the next run.
    loaded = False
    last_err: Optional[Exception] = None
    for attempt in range(2):
        try:
            page.goto(url, wait_until="load", timeout=25_000)
            wait_for_cloudflare(page)
            loaded = True
            break
        except Exception as e:
            last_err = e
            if attempt == 0:
                log.info(f"  Retry detail load: {url}")
                try:
                    page.wait_for_timeout(1_000)
                except Exception:
                    pass
    if not loaded:
        log.warning(f"Failed to load {url}: {last_err}")
        return {}

    delisted = _detect_delisted(page)
    data: dict = {"delisted": delisted}

    # ── Images (live pages only — delisted pages have no photo gallery) ─────────
    if not delisted:
        try:
            images = page.eval_on_selector_all(
                ".product-photos__list img, .product-photos img, .photo-gallery img",
                "els => els.map(e => e.getAttribute('src') || e.getAttribute('data-src') || '').filter(Boolean)"
            )
            seen = set()
            unique_images = []
            for img in images:
                if img not in seen and ("turbo.az" in img or img.startswith("https://")):
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
        data["drive_type"] = _find(specs, ["ötürücü", "drive", "привод"])
        data["doors"] = _parse_int(_find(specs, ["qapı sayı", "doors", "двери"]))
        data["vin"] = _find(specs, ["vin", "vin-kod"])
        data["condition"] = _find(specs, ["vəziyyəti", "condition", "состояние"])
        data["market_for"] = _find(
            specs, ["hansı bazar üçün yığılıb", "market", "рынок"]
        )
        data["city"] = _find(specs, ["şəhər", "city", "город", "şehər"])

        # Engine → (volume, hp, fuel_type). Keep the raw engine text too
        # (existing `engine` column holds the string form for display).
        engine_raw = _find(
            specs, ["mühərrik", "engine", "двигатель"]
        )
        engine_volume, hp, fuel_from_engine = parse_engine(engine_raw)
        data["engine"] = parse_engine_cc(engine_raw)
        data["engine_volume"] = engine_volume
        data["hp"] = hp

        # fuel_type: prefer dedicated spec field if present, else the last
        # segment of the engine value.
        data["fuel_type"] = (
            _find(specs, ["yanacaq", "fuel type", "mühərrik növü"])
            or fuel_from_engine
        )

        # Odometer from specs (for on-order listings where the listing-page
        # card didn't carry odometer; harmless for regular listings).
        odo_raw = _find(specs, ["yürüş", "mileage", "пробег"])
        odo_val, odo_type = _parse_odometer_spec(odo_raw)
        if odo_val is not None:
            data["odometer"] = odo_val
            data["odometer_type"] = odo_type
    except Exception as e:
        log.debug(f"Specs parse error for {url}: {e}")
        data["specs"] = {}

    # VIN fallback from the dedicated copy-block (some pages only render it here).
    if not data.get("vin"):
        try:
            vin_el = page.query_selector(".product-vin__title .js-copy-text")
            if vin_el:
                txt = (vin_el.inner_text() or "").strip()
                if txt:
                    data["vin"] = txt
        except Exception:
            pass

    # ── Description ─────────────────────────────────────────────────────────────
    try:
        desc_el = page.query_selector(".product-description__content, .product-text, .description")
        if desc_el:
            data["description"] = desc_el.inner_text().strip() or None
    except Exception:
        pass

    # ── Statistics strip (view count + date updated on turbo.az) ────────────────
    try:
        stat_texts = page.eval_on_selector_all(
            ".product-statistics__i-text",
            "els => els.map(e => e.textContent.trim())",
        )
        for text in stat_texts:
            m = re.search(r"baxışların sayı:\s*(\d+)", text, re.IGNORECASE)
            if m:
                data["view_count_scraped"] = int(m.group(1))
                continue
            m = re.search(r"yeniləndi:\s*(\d{2}\.\d{2}\.\d{4})", text, re.IGNORECASE)
            if m:
                data["date_updated_turbo"] = parse_turbo_date(m.group(1))
    except Exception as e:
        log.debug(f"Statistics parse error for {url}: {e}")

    # ── Features / labels / seller / on-order — live pages only ────────────────
    # These blocks live inside .product-sidebar__box which is absent on delisted
    # pages (its absence is one of our delisted detection signals).
    if not delisted:
        try:
            features = page.eval_on_selector_all(
                "ul.product-extras li.product-extras__i, .product-extras__i",
                "els => els.map(e => e.textContent.trim()).filter(Boolean)",
            )
            seen_f = set()
            dedup_f: list[str] = []
            for f in features:
                if f not in seen_f:
                    seen_f.add(f)
                    dedup_f.append(f)
            data["features"] = dedup_f
        except Exception as e:
            log.debug(f"Features parse error for {url}: {e}")
            data["features"] = []

        try:
            labels = page.eval_on_selector_all(
                ".product-labels .product-labels__i",
                "els => els.map(e => e.textContent.trim()).filter(Boolean)",
            )
            seen_l = set()
            dedup_l: list[str] = []
            for lbl in labels:
                if lbl not in seen_l:
                    seen_l.add(lbl)
                    dedup_l.append(lbl)
            data["labels"] = dedup_l
        except Exception as e:
            log.debug(f"Labels parse error for {url}: {e}")
            data["labels"] = []

        is_on_order = False
        try:
            is_on_order = page.query_selector(".product-shop__status_order") is not None
        except Exception:
            pass
        data["is_on_order"] = is_on_order
        if is_on_order:
            _fill_on_order_pricing(page, data)

        try:
            seller_data = _parse_seller(page)
            data["seller"] = seller_data
            if not data.get("city"):
                data["city"] = seller_data.get("city")
        except Exception as e:
            log.debug(f"Seller parse error for {url}: {e}")
            data["seller"] = {}
    else:
        is_on_order = False

    # ── Raw JSON dump (specs always, collections only when live) ─────────────────
    data["raw_detail_json"] = {
        "specs": data.get("specs", {}),
        "images": data.get("images", []),
        "features": data.get("features", []),
        "labels": data.get("labels", []),
        "is_on_order": is_on_order,
    }

    return data


def _fill_on_order_pricing(page: Page, data: dict) -> None:
    """
    On-order sidebars show pricing differently from the standard box:
      <div class="product-price__i product-price__i--bold">≈ 260 100 ₼</div>
      <div class="product-price__i tz-mt-10">153 000 USD</div>
    The bold line is the AZN estimate; the plain line is the list currency (USD
    in most cases). We take the USD value as the authoritative `price` +
    `currency`, and the AZN value as `price_azn`.
    """
    try:
        price_blocks = page.eval_on_selector_all(
            ".product-sidebar__box .product-price .product-price__i",
            """els => els.map(e => ({
                text: e.textContent.trim(),
                bold: e.classList.contains('product-price__i--bold'),
            }))""",
        )
    except Exception as e:
        log.debug(f"On-order pricing parse error: {e}")
        return

    bold_text = None
    plain_text = None
    for block in price_blocks:
        if block["bold"] and not bold_text:
            bold_text = block["text"]
        elif not block["bold"] and not plain_text:
            plain_text = block["text"]

    # Plain block is the primary list currency (e.g. "153 000 USD").
    if plain_text:
        price, currency = _parse_any_price(plain_text)
        if price is not None:
            data["price"] = price
            data["currency"] = currency
    # Bold block is the AZN estimate ("≈ 260 100 ₼").
    if bold_text:
        azn, cur = _parse_any_price(bold_text)
        if azn is not None and cur == "AZN":
            data["price_azn"] = float(azn)

    # Fallback: if we only extracted an AZN estimate, surface it as price too.
    if data.get("price") is None and data.get("price_azn") is not None:
        data["price"] = int(data["price_azn"])
        data["currency"] = "AZN"


def _parse_any_price(text: str) -> tuple[Optional[int], Optional[str]]:
    """Extract an integer + currency code from mixed-symbol text."""
    price, currency = parse_price(text)
    if price is not None:
        return price, currency
    # Fallback: "NNN USD" / "NNN EUR" / "NNN AZN" word forms.
    m = re.search(
        r"([\d\s]+)\s*(USD|EUR|AZN|RUB|GBP)\b",
        text,
        re.IGNORECASE,
    )
    if m:
        return (
            int(re.sub(r"\s", "", m.group(1))),
            m.group(2).upper(),
        )
    return None, None


def _parse_odometer_spec(raw: Optional[str]) -> tuple[Optional[int], Optional[str]]:
    """Parse '747 km' / '120 000 mi' → (747, 'km')."""
    if not raw:
        return None, None
    m = re.search(r"([\d\s]+)\s*(km|mi|км|mi\.)", raw, re.IGNORECASE)
    if not m:
        return None, None
    digits = re.sub(r"\s", "", m.group(1))
    if not digits:
        return None, None
    unit = m.group(2).lower()
    unit = "km" if unit.startswith("к") or unit == "km" else unit
    unit = "mi" if unit.startswith("mi") else unit
    return int(digits), unit


def _parse_seller(page: Page) -> dict:
    """
    Extract seller info from a turbo.az detail page.

    DOM reference (verified 2026-04):
      .product-owner (private-seller layout)
        .product-owner__info-name      → name
        .product-owner__info-region    → city
        .product-owner__info-regdate   → "Satıcı MM.YYYY tarixindən ..." (join date)

      .product-sidebar__box (shop / on-order layouts)
        .product-shop__owner-name      → shop name
        .product-shop__location        → city/address
        .product-shop__regdate         → "Satıcı MM.YYYY tarixindən ..."
        a[href^="/avtosalonlar/"]      → shop profile URL (Dilerə keç button)

      .product-phones.js-phone-reveal
        .product-phones__btn.js-phone-reveal-btn    → click to reveal
        .product-phones__list
          a.product-phones__list-i[href^="tel:"]    → phone numbers

      #chat-write-link
        data-user     → numeric turbo.az user id (stable per seller)
        data-receiver → JSON {id, name, phones: [...]}   (may leak phones)
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

    if not phones_raw and dr_phones:
        phones_raw = dr_phones

    seller["phones"] = phones_raw
    seller["phones_normalized"] = [
        p for p in (normalize_phone(x) for x in phones_raw) if p
    ]

    # ── Name / city / regdate from whichever block is present ───────────────
    # Private-seller block
    for sel, key in [
        (".product-owner__info-name", "name"),
        (".product-owner__info-region", "city"),
        (".product-owner__info-regdate", "regdate_raw"),
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

    # Shop / on-order block (also sets regdate if private block was absent)
    for sel, key in [
        (".product-shop__owner-name", "name"),
        (".product-shop__regdate", "regdate_raw"),
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

    # Shop location → split into city + address
    if not seller.get("city"):
        try:
            el = page.query_selector(".product-shop__location a")
            if el:
                loc_txt = (el.inner_text() or "").strip()
                if loc_txt:
                    city, address = parse_seller_location(loc_txt)
                    if city:
                        seller["city"] = city
                    if address:
                        seller["address"] = address
        except Exception:
            pass

    # Normalize regdate: "Satıcı 12.2025 tarixindən..." → date(2025, 12, 1)
    regdate = parse_regdate(seller.pop("regdate_raw", None))
    if regdate:
        seller["regdate"] = regdate

    # ── Profile URL (dealer shop link on /avtosalonlar/) ────────────────────
    profile_url = None
    try:
        el = page.query_selector(
            '.product-sidebar__box a[href^="/avtosalonlar/"], '
            'a.tz-btn--blue[href^="/avtosalonlar/"]'
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

    # ── Rough per-page type hint ────────────────────────────────────────────
    # Final business/dealer/private classification runs in seller_classifier
    # after the scrape; this is only a placeholder so new sellers aren't
    # immediately mislabeled.
    if profile_url and "/avtosalonlar/" in profile_url:
        seller["seller_type"] = "business"

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
