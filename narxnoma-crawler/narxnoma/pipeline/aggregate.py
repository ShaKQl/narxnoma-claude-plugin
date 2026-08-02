"""Stage 4: many offers for one product become the numbers a page shows.

Two rules here carry the product's promise:

**Only an in-stock offer may set the headline price.** An out-of-stock listing
is still recorded -- it is a real observation and price history needs it -- but
quoting it as the price would advertise something nobody can buy.

**The headline price remembers which listing it came from.** `min_store_id` and
`min_offer_id` are not bookkeeping; they are the feature. They are what lets a
product page print the retailer's own wording beside the number, so a shopper
can check the match themselves. A competitor cannot do that, which is precisely
how their colour-pooled prices go unnoticed.
"""
import logging
from dataclasses import dataclass

from narxnoma.matching import robust_median

logger = logging.getLogger(__name__)

# uzum is a multi-seller marketplace: one variant can carry dozens of listings
# from different sellers at wildly different prices. Below this many we report
# the plain figures, because IQR stripping on two or three samples discards
# real data rather than outliers.
MIN_SELLERS_FOR_SPREAD = 2


@dataclass(frozen=True)
class Spread:
    """What a multi-seller marketplace is actually charging for one variant."""

    min_price: int
    median_price: int
    max_price: int
    seller_count: int


def recompute_variant_prices(conn) -> int:
    """Rebuild every variant's price rollup from its current offers.

    Returns the number of variants written. Rebuilding wholesale rather than
    patching incrementally is deliberate: an offer that went out of stock, or
    was re-attached to a different variant by clustering, must not leave a
    stale headline price behind.
    """
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""
                WITH stats AS (
                    SELECT o.variant_id,
                           count(*) AS offer_count,
                           count(*) FILTER (WHERE o.availability = 'IN_STOCK')
                               AS in_stock_offer_count,
                           count(DISTINCT o.store_id) AS store_count,
                           min(o.price) FILTER (WHERE o.availability = 'IN_STOCK')
                               AS min_price,
                           max(o.price) FILTER (WHERE o.availability = 'IN_STOCK')
                               AS max_price,
                           percentile_disc(0.5) WITHIN GROUP (ORDER BY o.price)
                               FILTER (WHERE o.availability = 'IN_STOCK')
                               AS median_price
                      FROM offer o
                     WHERE o.variant_id IS NOT NULL
                     GROUP BY o.variant_id
                ),
                cheapest AS (
                    -- Which listing the headline price came from. DISTINCT ON
                    -- with a deterministic tiebreak so the provenance does not
                    -- flap between equal-priced offers on every run.
                    SELECT DISTINCT ON (o.variant_id)
                           o.variant_id, o.id AS offer_id, o.store_id
                      FROM offer o
                     WHERE o.variant_id IS NOT NULL
                       AND o.availability = 'IN_STOCK'
                     ORDER BY o.variant_id, o.price, o.id
                )
                INSERT INTO variant_price (
                    variant_id, min_price, min_store_id, min_offer_id,
                    median_price, max_price, offer_count, in_stock_offer_count,
                    store_count, computed_at)
                SELECT s.variant_id, s.min_price, c.store_id, c.offer_id,
                       s.median_price, s.max_price, s.offer_count,
                       s.in_stock_offer_count, s.store_count, now()
                  FROM stats s
                  LEFT JOIN cheapest c ON c.variant_id = s.variant_id
                ON CONFLICT (variant_id) DO UPDATE SET
                    min_price            = EXCLUDED.min_price,
                    min_store_id         = EXCLUDED.min_store_id,
                    min_offer_id         = EXCLUDED.min_offer_id,
                    median_price         = EXCLUDED.median_price,
                    max_price            = EXCLUDED.max_price,
                    offer_count          = EXCLUDED.offer_count,
                    in_stock_offer_count = EXCLUDED.in_stock_offer_count,
                    store_count          = EXCLUDED.store_count,
                    computed_at          = now()
            """)
            written = cur.rowcount

            # A variant whose offers all vanished must not keep a price.
            cur.execute("""
                DELETE FROM variant_price vp
                 WHERE NOT EXISTS (
                    SELECT 1 FROM offer o WHERE o.variant_id = vp.variant_id)
            """)

    logger.info("recomputed prices for %d variants", written)
    return written


def uzum_spread(conn, variant_id) -> Spread | None:
    """What uzum's sellers are charging for one variant.

    Returns None when uzum has too few listings for a spread to mean anything.
    The median is IQR-stripped because a marketplace carries both mis-listed
    accessories priced like phones and phones priced like accessories, and a
    single one of either would drag a plain median off the real market price.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT o.price FROM offer o
              JOIN store s ON s.id = o.store_id
             WHERE o.variant_id = %s AND s.slug = 'uzum'
               AND o.availability = 'IN_STOCK'
        """, (variant_id,))
        prices = [row[0] for row in cur.fetchall()]

    if len(prices) < MIN_SELLERS_FOR_SPREAD:
        return None

    median, kept = robust_median(prices)
    return Spread(
        min_price=min(prices),
        median_price=int(median),
        max_price=max(prices),
        seller_count=len(prices),
    )
