"""
Seller classification — reassigns sellers.seller_type after each scrape.

Per business rules:
  - business: seller has a /avtosalonlar/ shop page (verified via profile_url)
  - dealer:   no shop page, but lifetime listing count (active + sold) > 1
  - private:  everyone else

Runs once at the end of the lifecycle chord so the buckets always reflect the
freshly-observed state of the world. Three bulk UPDATEs — cheap even at scale.
"""
import logging

from psycopg2.extensions import connection as PGConnection

log = logging.getLogger(__name__)


def reclassify_sellers(conn: PGConnection) -> dict[str, int]:
    """
    Reassign seller_type for every seller based on current shop link +
    listing-count state. Returns a {type: count} summary for logging.
    """
    shop_like = "%/avtosalonlar/%"

    with conn.cursor() as cur:
        # 1. business — any shop link wins.
        cur.execute(
            """
            UPDATE sellers
               SET seller_type = 'business'
             WHERE profile_url LIKE %s
               AND (seller_type IS DISTINCT FROM 'business')
            """,
            (shop_like,),
        )
        n_business = cur.rowcount

        # 2. dealer — no shop link, but >1 lifetime listing (active + sold).
        cur.execute(
            """
            UPDATE sellers
               SET seller_type = 'dealer'
             WHERE (profile_url IS NULL OR profile_url NOT LIKE %s)
               AND (COALESCE(total_listings, 0) + COALESCE(total_sold, 0)) > 1
               AND (seller_type IS DISTINCT FROM 'dealer')
            """,
            (shop_like,),
        )
        n_dealer = cur.rowcount

        # 3. private — everything else with ≤1 lifetime listing.
        cur.execute(
            """
            UPDATE sellers
               SET seller_type = 'private'
             WHERE (profile_url IS NULL OR profile_url NOT LIKE %s)
               AND (COALESCE(total_listings, 0) + COALESCE(total_sold, 0)) <= 1
               AND (seller_type IS DISTINCT FROM 'private')
            """,
            (shop_like,),
        )
        n_private = cur.rowcount

    conn.commit()
    summary = {"business": n_business, "dealer": n_dealer, "private": n_private}
    log.info(
        "Seller reclassification: "
        f"business={n_business} dealer={n_dealer} private={n_private}"
    )
    return summary
