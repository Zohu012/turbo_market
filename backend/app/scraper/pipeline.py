"""
Pipeline orchestrator — sequences listing scan → detail fetch → DB upsert.

Used by Celery tasks; handles DB interactions for the listing phase.
All DB operations use a synchronous psycopg2 connection to avoid event-loop issues
inside Celery workers (Celery uses threads, not async).
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras
from psycopg2.extensions import connection as PGConnection

from app.config import settings
from app.scraper.listing_scraper import to_price_azn

log = logging.getLogger(__name__)


def get_sync_conn() -> PGConnection:
    dsn = settings.sync_database_url.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(dsn)


# ── Vehicle lifecycle helpers ───────────────────────────────────────────────────

def _build_reactivation_fields(
    cur,
    vehicle_id: int,
    now: datetime,
    last_activated_at,
    date_added,
    active_days_accumulated: Optional[int],
) -> dict:
    """Compute the field overrides for an inactive → active flip.

    Reads `date_deactivated` to compute the length of the previous active
    window, accumulates it into `active_days_accumulated`, and resets the
    anchor. Both the listing path (upsert_listing) and the details path
    (update_vehicle_detail) call this so reactivation math stays consistent.
    """
    cur.execute(
        "SELECT date_deactivated FROM vehicles WHERE id = %s", (vehicle_id,)
    )
    dd_row = cur.fetchone()
    date_deactivated = dd_row["date_deactivated"] if dd_row else None

    anchor = last_activated_at or date_added
    prev_window = 0
    if anchor and date_deactivated and date_deactivated > anchor:
        prev_window = (date_deactivated - anchor).days
    return {
        "active_days_accumulated": (active_days_accumulated or 0) + prev_window,
        "last_activated_at": now,
        "date_deactivated": None,
        "days_to_sell": None,
        "status": "active",
        "missing_scan_count": 0,
    }


# ── Vehicle upsert ──────────────────────────────────────────────────────────────

def upsert_listing(
    conn: PGConnection,
    vehicle: dict,
    session_start: Optional[datetime] = None,
) -> tuple[int, str, bool, bool]:
    """
    Insert or update a vehicle from listing card data.

    `session_start` (optional): the started_at of the current scrape session.
    When provided, `last_seen_at` is set to that value on both INSERT and UPDATE
    paths so Phase 2 classification can identify rows absent from this session
    via `last_seen_at < session_start`. Falls back to now() when omitted (keeps
    callers that don't track sessions — e.g. Celery's scrape_make_task — working).

    Returns (vehicle_id, action, price_changed, needs_detail):
      action         = 'new' | 'updated' | 'unchanged'
      price_changed  = True if price was recorded in price_history
      needs_detail   = True if the caller should fetch the detail page
                       (new row, or date_updated_turbo drift)
    """
    turbo_id = vehicle["turbo_id"]
    now = datetime.now(timezone.utc)
    last_seen_stamp = session_start or now
    listing_dt = vehicle.get("date_updated_turbo")

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, price, currency, odometer, odometer_type, status,
                   date_updated_turbo, active_days_accumulated, last_activated_at,
                   date_added
              FROM vehicles
             WHERE turbo_id = %s
            """,
            (turbo_id,),
        )
        row = cur.fetchone()

        if row is None:
            # ── New vehicle ────────────────────────────────────────────────
            # needs_detail_refresh=TRUE so the next Details Update run picks it up.
            cur.execute(
                """
                INSERT INTO vehicles
                  (turbo_id, make, model, year, price, currency, price_azn,
                   odometer, odometer_type, engine, url, status,
                   date_added, date_updated, date_updated_turbo,
                   last_activated_at, last_seen_at, needs_detail_refresh)
                VALUES
                  (%(turbo_id)s, %(make)s, %(model)s, %(year)s, %(price)s,
                   %(currency)s, %(price_azn)s, %(odometer)s, %(odometer_type)s,
                   %(engine)s, %(url)s, 'active',
                   %(now)s, %(now)s, %(date_updated_turbo)s,
                   %(now)s, %(last_seen_at)s, TRUE)
                RETURNING id
                """,
                {
                    **vehicle,
                    "now": now,
                    "date_updated_turbo": listing_dt,
                    "last_seen_at": last_seen_stamp,
                },
            )
            vehicle_id = cur.fetchone()["id"]
            conn.commit()
            return vehicle_id, "new", False, True

        vehicle_id = row["id"]

        # ── Existing vehicle: detect drifts ───────────────────────────────
        price_changed = (
            vehicle.get("price") is not None
            and (
                row["price"] != vehicle["price"]
                or row["currency"] != vehicle["currency"]
            )
        )
        odometer_changed = (
            vehicle.get("odometer") is not None
            and row["odometer"] is not None
            and row["odometer"] != vehicle["odometer"]
        )

        # Freshness check: re-fetch detail only if turbo.az's own "Yeniləndi"
        # timestamp moved. A new row always needs a detail; a repost does too.
        needs_detail = False
        if listing_dt is not None:
            if row["date_updated_turbo"] is None or row["date_updated_turbo"] != listing_dt:
                needs_detail = True

        # Price history
        if price_changed:
            cur.execute(
                """
                INSERT INTO price_history (vehicle_id, price, currency, price_azn, recorded_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    vehicle_id,
                    row["price"],
                    row["currency"],
                    to_price_azn(row["price"], row["currency"]),
                    now,
                ),
            )

        # Odometer history — record the OLD value before overwriting.
        if odometer_changed:
            cur.execute(
                """
                INSERT INTO odometer_history (vehicle_id, odometer, odometer_type, recorded_at)
                VALUES (%s, %s, %s, %s)
                """,
                (vehicle_id, row["odometer"], row["odometer_type"], now),
            )

        # Reactivation: inactive → active. Accumulate the previous active
        # window into active_days_accumulated and reset the anchor. Helper
        # is shared with update_vehicle_detail's reactivation path.
        extra: dict = {}
        reactivated = row["status"] == "inactive"
        if reactivated:
            extra = _build_reactivation_fields(
                cur,
                vehicle_id,
                now,
                row["last_activated_at"],
                row["date_added"],
                row["active_days_accumulated"],
            )
            needs_detail = True  # Always re-fetch detail on reactivation.

        update_fields = {
            "price": vehicle.get("price"),
            "currency": vehicle.get("currency"),
            "price_azn": vehicle.get("price_azn"),
            "odometer": vehicle.get("odometer"),
            "odometer_type": vehicle.get("odometer_type"),
            "date_updated": now,
            # Card is present → this listing is still live → reset the miss
            # counter used by two-miss sold detection in lifecycle.py.
            "missing_scan_count": 0,
            # Per-session sighting stamp — Phase 2 classifier compares rows
            # against session_start to find those absent from this run.
            "last_seen_at": last_seen_stamp,
            **extra,
        }
        if listing_dt is not None:
            update_fields["date_updated_turbo"] = listing_dt
        # Queue the row for Details Update if turbo.az signalled a refresh
        # (date_updated_turbo drift) or the row just reactivated.
        if needs_detail:
            update_fields["needs_detail_refresh"] = True

        # Filter out keys whose value is None AND we don't care about
        # overwriting with null — keep explicit Nones we set in `extra`.
        writeable = {
            k: v
            for k, v in update_fields.items()
            if v is not None or k in {"date_deactivated", "days_to_sell"}
        }
        set_clause = ", ".join(f"{k} = %({k})s" for k in writeable)
        cur.execute(
            f"UPDATE vehicles SET {set_clause} WHERE id = %(vehicle_id)s",
            {**writeable, "vehicle_id": vehicle_id},
        )
        conn.commit()

        action: str
        if price_changed or odometer_changed or reactivated:
            action = "updated"
        else:
            action = "unchanged"
        return vehicle_id, action, price_changed, needs_detail


def update_vehicle_detail(
    conn: PGConnection,
    vehicle_id: int,
    detail: dict,
    preserve_collections_if_shorter: bool = False,
):
    """Apply detail page data (specs, images, seller, features, labels) to an existing vehicle.

    preserve_collections_if_shorter: when True, skip image/feature/label replacement
    if the freshly-scraped list is strictly shorter than what's already stored.
    Used by Details Full so thin re-scrapes (common on inactive listings) don't
    erase historical data.
    """
    if not detail:
        return

    now = datetime.now(timezone.utc)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # ── Read current lifecycle state in one roundtrip ────────────────
        # We fetch view-count fields + reactivation fields together so the
        # details-path reactivation logic below can run without a second
        # SELECT. Reactivation fires when a previously-inactive row turns
        # out to have a healthy detail page (seller block present, no
        # delisted marker) — guards against the false-positive deactivations
        # that the listing-path two-miss safety net produces during
        # CF-blocked partial runs.
        cur.execute(
            "SELECT view_count_base, last_scraped_view_count, "
            "       status, last_activated_at, active_days_accumulated, "
            "       date_added "
            "FROM vehicles WHERE id = %s",
            (vehicle_id,),
        )
        lifecycle_row = cur.fetchone() or {}

        # ── View count bookkeeping (cumulative on repost) ────────────────
        scraped_vc = detail.get("view_count_scraped")
        effective_vc: Optional[int] = None
        if scraped_vc is not None:
            row = lifecycle_row
            base = row.get("view_count_base") or 0
            last_scraped = row.get("last_scraped_view_count")

            # Reset detection: the raw number went DOWN. Treat the prior
            # scraped value as the final count of the previous activation,
            # move it into view_count_history, and fold it into the base.
            if last_scraped is not None and scraped_vc < last_scraped:
                cur.execute(
                    "INSERT INTO view_count_history (vehicle_id, view_count, recorded_at) "
                    "VALUES (%s, %s, %s)",
                    (vehicle_id, last_scraped, now),
                )
                base = base + last_scraped
            # When the raw number grew but is "significantly" different
            # (e.g. 0 on repost is handled above; otherwise we just update).

            effective_vc = base + scraped_vc

            cur.execute(
                "UPDATE vehicles SET view_count_base = %s, last_scraped_view_count = %s "
                "WHERE id = %s",
                (base, scraped_vc, vehicle_id),
            )

        # ── Vehicle field map ────────────────────────────────────────────
        fields: dict = {
            "color": detail.get("color"),
            "body_type": detail.get("body_type"),
            "transmission": detail.get("transmission"),
            "fuel_type": detail.get("fuel_type"),
            "drive_type": detail.get("drive_type"),
            "doors": detail.get("doors"),
            "vin": detail.get("vin"),
            "hp": detail.get("hp"),
            "condition": detail.get("condition"),
            "market_for": detail.get("market_for"),
            "description": detail.get("description"),
            "city": detail.get("city"),
            "raw_detail_json": psycopg2.extras.Json(detail.get("raw_detail_json")),
            "date_updated": now,
        }
        if effective_vc is not None:
            fields["view_count"] = effective_vc
        if detail.get("date_updated_turbo") is not None:
            fields["date_updated_turbo"] = detail["date_updated_turbo"]
        if detail.get("is_on_order") is not None:
            fields["is_on_order"] = bool(detail.get("is_on_order"))

        # On-order listings: listing cards had no price/odometer, so the
        # detail page is where they first land.
        if detail.get("is_on_order"):
            if detail.get("price") is not None:
                fields["price"] = detail["price"]
                fields["currency"] = detail.get("currency")
                if detail.get("price_azn") is not None:
                    fields["price_azn"] = detail["price_azn"]
                else:
                    fields["price_azn"] = to_price_azn(
                        detail["price"], detail.get("currency")
                    )
            if detail.get("odometer") is not None:
                fields["odometer"] = detail["odometer"]
                fields["odometer_type"] = detail.get("odometer_type")
            if detail.get("engine") is not None:
                fields["engine"] = detail["engine"]

        seller = detail.get("seller", {})
        seller_id = upsert_seller(conn, seller) if seller else None
        if seller_id:
            fields["seller_id"] = seller_id
            # last_seen only (total_listings is incremented on the "new" branch
            # of upsert_listing; incrementing here double-counts on re-scrapes).
            cur.execute(
                "UPDATE sellers SET last_seen = %s WHERE id = %s",
                (now, seller_id),
            )

        # ── Reactivation (details-path) ──────────────────────────────────
        # If the row was previously deactivated but the detail page proves
        # it's alive (seller block rendered + parsed AND no delisted marker),
        # flip it back to active. Mirrors upsert_listing's reactivation but
        # triggered by a healthy detail fetch instead of a listing sighting.
        # This is what heals false-positive deactivations from CF-blocked
        # listing runs without forcing the user to re-run --listing-make.
        if (
            lifecycle_row.get("status") == "inactive"
            and seller_id is not None
            and not detail.get("delisted")
        ):
            reactivation = _build_reactivation_fields(
                cur,
                vehicle_id,
                now,
                lifecycle_row.get("last_activated_at"),
                lifecycle_row.get("date_added"),
                lifecycle_row.get("active_days_accumulated"),
            )
            fields.update(reactivation)
            # Stamp last_seen_at so the next listing pass doesn't immediately
            # re-flag this row as a delist suspect on `last_seen_at < session_start`.
            fields["last_seen_at"] = now
            log.info(
                f"  Reactivated vehicle {vehicle_id} via details path "
                f"(was inactive, detail page healthy)"
            )

        # Keep explicit None values for known-nullable lifecycle columns so
        # the reactivation block above can clear date_deactivated and
        # days_to_sell. All other Nones are filtered (we don't want to wipe
        # color/vin/etc. just because the detail scrape didn't return them).
        _NULLABLE_LIFECYCLE = {"date_deactivated", "days_to_sell"}
        writeable = {
            k: v
            for k, v in fields.items()
            if v is not None or k in _NULLABLE_LIFECYCLE
        }
        set_clause = ", ".join(f"{k} = %({k})s" for k in writeable)
        if set_clause:
            cur.execute(
                f"UPDATE vehicles SET {set_clause} WHERE id = %(vehicle_id)s",
                {**writeable, "vehicle_id": vehicle_id},
            )

        # ── Images ───────────────────────────────────────────────────────
        images = detail.get("images", [])
        should_replace_images = bool(images)
        if should_replace_images and preserve_collections_if_shorter:
            cur.execute(
                "SELECT COUNT(*) AS n FROM vehicle_images WHERE vehicle_id = %s",
                (vehicle_id,),
            )
            existing_n = (cur.fetchone() or {}).get("n", 0)
            if len(images) < existing_n:
                should_replace_images = False
        if should_replace_images:
            cur.execute("DELETE FROM vehicle_images WHERE vehicle_id = %s", (vehicle_id,))
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO vehicle_images (vehicle_id, url, position, is_primary) VALUES %s",
                [
                    (vehicle_id, url, pos, pos == 0)
                    for pos, url in enumerate(images)
                ],
            )

        # ── Features / labels (M2M) ──────────────────────────────────────
        _replace_m2m(
            cur, vehicle_id, detail.get("features", []),
            "features", "vehicle_features", "feature_id",
            preserve_if_shorter=preserve_collections_if_shorter,
        )
        _replace_m2m(
            cur, vehicle_id, detail.get("labels", []),
            "labels", "vehicle_labels", "label_id",
            preserve_if_shorter=preserve_collections_if_shorter,
        )

        conn.commit()


def persist_view_count(
    conn: PGConnection, vehicle_id: int, scraped_vc: Optional[int]
) -> None:
    """
    Persist a scraped view count with cumulative-across-relistings bookkeeping.

    Extracted from update_vehicle_detail so lifecycle can capture a final VC
    snapshot on delisting WITHOUT triggering the full detail-update path
    (which wipes M2M rows and raw_detail_json when called with a minimal dict).
    """
    if scraped_vc is None:
        return

    now = datetime.now(timezone.utc)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT view_count_base, last_scraped_view_count "
            "FROM vehicles WHERE id = %s",
            (vehicle_id,),
        )
        row = cur.fetchone() or {}
        base = row.get("view_count_base") or 0
        last_scraped = row.get("last_scraped_view_count")

        # Reset detection (raw number went DOWN on a repost): fold prior
        # value into the base and archive it to view_count_history.
        if last_scraped is not None and scraped_vc < last_scraped:
            cur.execute(
                "INSERT INTO view_count_history (vehicle_id, view_count, recorded_at) "
                "VALUES (%s, %s, %s)",
                (vehicle_id, last_scraped, now),
            )
            base = base + last_scraped

        effective_vc = base + scraped_vc
        cur.execute(
            "UPDATE vehicles "
            "SET view_count_base = %s, last_scraped_view_count = %s, "
            "    view_count = %s "
            "WHERE id = %s",
            (base, scraped_vc, effective_vc, vehicle_id),
        )
        conn.commit()


def mark_delisted(conn: PGConnection, vehicle_id: int) -> None:
    """
    Mark a vehicle as sold/delisted WITHOUT overwriting its existing data.

    Freezes days_to_sell = active_days_accumulated + (now - last_activated_at).
    Called when the detail page shows any delisted marker (status-message,
    overlay, or missing sidebar) even if the turbo_id still appears in the
    listing scan.
    """
    now = datetime.now(timezone.utc)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT status, active_days_accumulated, last_activated_at, date_added, seller_id "
            "FROM vehicles WHERE id = %s",
            (vehicle_id,),
        )
        row = cur.fetchone()
        if not row:
            return
        if row["status"] == "inactive":
            return  # Already delisted — don't re-freeze days_to_sell.

        anchor = row["last_activated_at"] or row["date_added"]
        window = (now - anchor).days if anchor and now > anchor else 0
        days_to_sell = (row["active_days_accumulated"] or 0) + window

        cur.execute(
            """
            UPDATE vehicles
               SET status = 'inactive',
                   date_deactivated = %s,
                   date_updated = %s,
                   days_to_sell = %s
             WHERE id = %s
            """,
            (now, now, days_to_sell, vehicle_id),
        )
        if row["seller_id"]:
            cur.execute(
                "UPDATE sellers SET total_sold = total_sold + 1 WHERE id = %s",
                (row["seller_id"],),
            )
        conn.commit()


def clear_needs_detail_refresh(conn: PGConnection, vehicle_id: int) -> None:
    """Clear the Details-Update queue flag after a row has been processed."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE vehicles SET needs_detail_refresh = FALSE WHERE id = %s",
            (vehicle_id,),
        )
    conn.commit()


def upsert_seller(conn: PGConnection, seller: dict) -> Optional[int]:
    """
    Find or create a seller and return its id.

    Identity resolution (in order):
      1. turbo_seller_id (stable, unique per turbo.az account)
      2. any normalized phone (phones_normalized unique index)
      3. new row

    On match, merges any newly-seen phones. Safe to call repeatedly.
    """
    turbo_id = seller.get("turbo_seller_id")
    phones_raw = seller.get("phones", []) or []
    phones_norm = [p for p in (seller.get("phones_normalized") or []) if len(p) >= 7]

    if not turbo_id and not phones_norm:
        return None

    now = datetime.now(timezone.utc)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        seller_id = None

        if turbo_id:
            cur.execute(
                "SELECT id FROM sellers WHERE turbo_seller_id = %s", (turbo_id,)
            )
            row = cur.fetchone()
            if row:
                seller_id = row["id"]

        if seller_id is None and phones_norm:
            cur.execute(
                "SELECT seller_id FROM seller_phones WHERE normalized = ANY(%s) LIMIT 1",
                (phones_norm,),
            )
            row = cur.fetchone()
            if row:
                seller_id = row["seller_id"]

        if seller_id is not None:
            updates = {"last_seen": now}
            for k in ("name", "seller_type", "city", "address", "profile_url", "regdate"):
                v = seller.get(k)
                if v:
                    updates[k] = v
            if turbo_id:
                updates["turbo_seller_id"] = turbo_id
            set_clause = ", ".join(f"{k} = %({k})s" for k in updates)
            cur.execute(
                f"UPDATE sellers SET {set_clause} WHERE id = %(id)s",
                {**updates, "id": seller_id},
            )
        else:
            cur.execute(
                """
                INSERT INTO sellers
                  (turbo_seller_id, name, seller_type, city, address, profile_url,
                   regdate, first_seen, last_seen, total_listings)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                RETURNING id
                """,
                (
                    turbo_id,
                    seller.get("name"),
                    seller.get("seller_type"),
                    seller.get("city"),
                    seller.get("address"),
                    seller.get("profile_url"),
                    seller.get("regdate"),
                    now,
                    now,
                ),
            )
            seller_id = cur.fetchone()["id"]

        # Merge phones (normalized has a unique index — ON CONFLICT no-op)
        for raw, norm in zip(phones_raw, phones_norm):
            cur.execute(
                """
                INSERT INTO seller_phones (seller_id, phone, normalized)
                VALUES (%s, %s, %s) ON CONFLICT (normalized) DO NOTHING
                """,
                (seller_id, raw, norm),
            )

        conn.commit()
        return seller_id


def increment_seller_listings(conn: PGConnection, seller_id: int) -> None:
    """Bump total_listings by 1. Called by the caller on the 'new' branch
    of upsert_listing once a seller_id is known via detail fetch."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sellers SET total_listings = total_listings + 1 WHERE id = %s",
            (seller_id,),
        )
    conn.commit()


# ── M2M helper ──────────────────────────────────────────────────────────────────

def _replace_m2m(
    cur,
    vehicle_id: int,
    names: list[str],
    dim_table: str,
    join_table: str,
    join_fk: str,
    preserve_if_shorter: bool = False,
) -> None:
    """
    Replace the set of M2M rows for a vehicle. Upserts names into the dim
    table, then rewrites the join rows.

    preserve_if_shorter: when True, skip the replace entirely if the new
    `names` list is strictly shorter than the existing join-row count. Used
    by --full-details to avoid erasing features/labels on thin re-scrapes.
    """
    # Strip empties and dedupe while preserving order.
    seen: set[str] = set()
    clean: list[str] = []
    for n in names or []:
        n = (n or "").strip()
        if n and n not in seen:
            seen.add(n)
            clean.append(n)

    if preserve_if_shorter:
        cur.execute(
            f"SELECT COUNT(*) AS n FROM {join_table} WHERE vehicle_id = %s",
            (vehicle_id,),
        )
        existing_n = (cur.fetchone() or {}).get("n", 0)
        if len(clean) < existing_n:
            return

    # Always clear the join rows for this vehicle — even if `clean` is empty,
    # a vehicle that previously had features can have them removed.
    cur.execute(f"DELETE FROM {join_table} WHERE vehicle_id = %s", (vehicle_id,))
    if not clean:
        return

    # Upsert dim rows, then read back ids.
    psycopg2.extras.execute_values(
        cur,
        f"INSERT INTO {dim_table} (name) VALUES %s ON CONFLICT (name) DO NOTHING",
        [(n,) for n in clean],
    )
    cur.execute(
        f"SELECT id, name FROM {dim_table} WHERE name = ANY(%s)",
        (clean,),
    )
    id_by_name = {r["name"]: r["id"] for r in cur.fetchall()}

    rows = [(vehicle_id, id_by_name[n]) for n in clean if n in id_by_name]
    if rows:
        psycopg2.extras.execute_values(
            cur,
            f"INSERT INTO {join_table} (vehicle_id, {join_fk}) VALUES %s "
            f"ON CONFLICT DO NOTHING",
            rows,
        )
