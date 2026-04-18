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


# ── Vehicle upsert ──────────────────────────────────────────────────────────────

def upsert_listing(conn: PGConnection, vehicle: dict) -> tuple[str, bool]:
    """
    Insert or update a vehicle from listing card data.

    Returns (action, price_changed):
      action = 'new' | 'updated' | 'unchanged'
      price_changed = True if price was recorded in price_history
    """
    turbo_id = vehicle["turbo_id"]
    now = datetime.now(timezone.utc)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, price, currency, status FROM vehicles WHERE turbo_id = %s",
            (turbo_id,),
        )
        row = cur.fetchone()

        if row is None:
            # New vehicle
            cur.execute(
                """
                INSERT INTO vehicles
                  (turbo_id, make, model, year, price, currency, price_azn,
                   odometer, odometer_type, engine, url, status, date_added, date_updated)
                VALUES
                  (%(turbo_id)s, %(make)s, %(model)s, %(year)s, %(price)s,
                   %(currency)s, %(price_azn)s, %(odometer)s, %(odometer_type)s,
                   %(engine)s, %(url)s, 'active', %(now)s, %(now)s)
                RETURNING id
                """,
                {**vehicle, "now": now},
            )
            vehicle_id = cur.fetchone()["id"]
            conn.commit()
            return vehicle_id, "new", False

        vehicle_id = row["id"]

        # Check price change
        price_changed = (
            vehicle.get("price") is not None
            and (row["price"] != vehicle["price"] or row["currency"] != vehicle["currency"])
        )

        if price_changed:
            # Record old price in history
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

        # Re-activate if it was marked inactive (reposted listing)
        extra = {}
        if row["status"] == "inactive":
            extra["date_deactivated"] = None
            extra["status"] = "active"

        update_fields = {
            "price": vehicle.get("price"),
            "currency": vehicle.get("currency"),
            "price_azn": vehicle.get("price_azn"),
            "date_updated": now,
            **extra,
        }
        set_clause = ", ".join(f"{k} = %({k})s" for k in update_fields)
        cur.execute(
            f"UPDATE vehicles SET {set_clause} WHERE id = %(vehicle_id)s",
            {**update_fields, "vehicle_id": vehicle_id},
        )
        conn.commit()
        action = "updated" if price_changed or extra else "unchanged"
        return vehicle_id, action, price_changed


def update_vehicle_detail(conn: PGConnection, vehicle_id: int, detail: dict):
    """Apply detail page data (specs, images, seller) to an existing vehicle."""
    if not detail:
        return

    now = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        # Update vehicle fields from detail
        fields = {
            "color": detail.get("color"),
            "body_type": detail.get("body_type"),
            "transmission": detail.get("transmission"),
            "fuel_type": detail.get("fuel_type"),
            "drive_type": detail.get("drive_type"),
            "doors": detail.get("doors"),
            "vin": detail.get("vin"),
            "description": detail.get("description"),
            "view_count": detail.get("view_count"),
            "city": detail.get("city"),
            "raw_detail_json": psycopg2.extras.Json(detail.get("raw_detail_json")),
            "date_updated": now,
        }

        seller = detail.get("seller", {})
        seller_id = upsert_seller(conn, seller) if seller else None
        if seller_id:
            fields["seller_id"] = seller_id
            # Increment total_listings
            cur.execute(
                "UPDATE sellers SET total_listings = total_listings + 1, last_seen = %s WHERE id = %s",
                (now, seller_id),
            )

        set_clause = ", ".join(f"{k} = %({k})s" for k in fields if fields[k] is not None)
        if set_clause:
            cur.execute(
                f"UPDATE vehicles SET {set_clause} WHERE id = %(vehicle_id)s",
                {k: v for k, v in fields.items() if v is not None} | {"vehicle_id": vehicle_id},
            )

        # Insert images (skip if already exist)
        images = detail.get("images", [])
        if images:
            cur.execute("DELETE FROM vehicle_images WHERE vehicle_id = %s", (vehicle_id,))
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO vehicle_images (vehicle_id, url, position, is_primary) VALUES %s",
                [
                    (vehicle_id, url, pos, pos == 0)
                    for pos, url in enumerate(images)
                ],
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
            # Update mutable fields (only if new value is non-null)
            updates = {"last_seen": now}
            for k in ("name", "seller_type", "city", "profile_url"):
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
                  (turbo_seller_id, name, seller_type, city, profile_url, first_seen, last_seen)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    turbo_id,
                    seller.get("name"),
                    seller.get("seller_type", "private"),
                    seller.get("city"),
                    seller.get("profile_url"),
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
