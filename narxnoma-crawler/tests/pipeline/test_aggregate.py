"""Aggregation: which number a page shows, and which listing it came from."""
import pytest

from narxnoma.db import repository as repo
from narxnoma.pipeline.aggregate import recompute_variant_prices, uzum_spread
from narxnoma.pipeline.cluster import cluster_offers
from narxnoma.pipeline.extract import identify
from narxnoma.sources.base import Listing

pytestmark = pytest.mark.db


def seed(conn, name, key, store="olcha", price=2_723_000, availability="IN_STOCK"):
    ids = repo.store_ids(conn)
    repo.upsert_offers(conn, ids[store], [Listing(
        store_slug=store, source_key=key, name_raw=name, price=price,
        url=f"https://{store}.uz/{key}", availability=availability)])
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM offer WHERE source_key = %s AND store_id = %s",
                    (key, ids[store]))
        return cur.fetchone()[0]


def cluster(conn):
    cluster_offers(conn, (identify(r) for r in repo.load_unattached_offers(conn)))


def price_row(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT min_price, median_price, max_price, offer_count,
                   in_stock_offer_count, store_count, min_store_id, min_offer_id
              FROM variant_price
        """)
        return cur.fetchone()


HONOR = "Смартфон Honor X9d 12/256 ГБ, черный"


def test_single_offer_variant_has_min_equal_median_equal_max(db_conn):
    seed(db_conn, HONOR, "a", price=4_839_000)
    cluster(db_conn)
    recompute_variant_prices(db_conn)

    lo, med, hi, offers, in_stock, stores, *_ = price_row(db_conn)
    assert lo == med == hi == 4_839_000
    assert offers == in_stock == stores == 1


def test_out_of_stock_offer_never_becomes_the_headline_price(db_conn):
    # A cheaper listing nobody can buy must not be advertised as the price.
    seed(db_conn, HONOR, "cheap", price=3_000_000, availability="OUT_OF_STOCK")
    seed(db_conn, HONOR, "real", store="idea", price=4_839_000)
    cluster(db_conn)
    recompute_variant_prices(db_conn)

    lo, _, _, offers, in_stock, _, _, _ = price_row(db_conn)
    assert lo == 4_839_000, "the out-of-stock 3,000,000 must not win"
    assert offers == 2, "but it is still counted as an observation"
    assert in_stock == 1


def test_headline_price_records_which_listing_it_came_from(db_conn):
    # The provenance IS the feature: it lets a page quote the retailer's own
    # wording beside the number so a shopper can check the match themselves.
    seed(db_conn, HONOR, "dear", price=5_500_000)
    cheapest = seed(db_conn, HONOR, "cheap", store="idea", price=4_839_000)
    cluster(db_conn)
    recompute_variant_prices(db_conn)

    lo, _, _, _, _, _, min_store, min_offer = price_row(db_conn)
    assert lo == 4_839_000
    assert min_offer == cheapest
    with db_conn.cursor() as cur:
        cur.execute("SELECT slug FROM store WHERE id = %s", (min_store,))
        assert cur.fetchone()[0] == "idea"


def test_a_variant_with_no_in_stock_offers_has_no_headline_price(db_conn):
    # min_price is nullable precisely so this case does not force us to either
    # publish an unbuyable price or delete the variant's row.
    seed(db_conn, HONOR, "gone", price=4_839_000, availability="OUT_OF_STOCK")
    cluster(db_conn)
    recompute_variant_prices(db_conn)

    lo, _, _, offers, in_stock, _, _, _ = price_row(db_conn)
    assert lo is None
    assert offers == 1 and in_stock == 0


def test_recompute_is_idempotent_and_reflects_stock_changes(db_conn):
    offer_id = seed(db_conn, HONOR, "a", price=4_839_000)
    cluster(db_conn)
    recompute_variant_prices(db_conn)
    assert price_row(db_conn)[0] == 4_839_000

    # The offer goes out of stock; the stale headline must not survive.
    with db_conn.cursor() as cur:
        cur.execute("UPDATE offer SET availability = 'OUT_OF_STOCK' WHERE id = %s",
                    (offer_id,))
    recompute_variant_prices(db_conn)
    assert price_row(db_conn)[0] is None

    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM variant_price")
        assert cur.fetchone()[0] == 1, "recompute must not duplicate rows"


def test_uzum_spread_strips_an_outlier_from_the_median(db_conn):
    # A marketplace carries mis-listed items priced like phones. One of them
    # must not drag the median off the real market price.
    for i, price in enumerate([4_800_000, 4_850_000, 4_900_000, 4_950_000, 40_000_000]):
        seed(db_conn, HONOR, f"u{i}", store="uzum", price=price)
    cluster(db_conn)

    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM variant")
        variant_id = cur.fetchone()[0]

    spread = uzum_spread(db_conn, variant_id)
    assert spread.seller_count == 5
    assert spread.min_price == 4_800_000
    assert spread.max_price == 40_000_000, "the outlier is still reported as the max"
    assert spread.median_price < 5_000_000, "but it must not drag the median"


def test_uzum_spread_is_none_when_there_is_no_spread_to_report(db_conn):
    seed(db_conn, HONOR, "solo", store="uzum", price=4_839_000)
    cluster(db_conn)
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM variant")
        variant_id = cur.fetchone()[0]
    assert uzum_spread(db_conn, variant_id) is None


def test_spread_ignores_other_stores(db_conn):
    seed(db_conn, HONOR, "u1", store="uzum", price=4_800_000)
    seed(db_conn, HONOR, "u2", store="uzum", price=4_900_000)
    seed(db_conn, HONOR, "other", store="olcha", price=9_000_000)
    cluster(db_conn)
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM variant")
        variant_id = cur.fetchone()[0]

    spread = uzum_spread(db_conn, variant_id)
    assert spread.seller_count == 2
    assert spread.max_price == 4_900_000, "olcha's 9,000,000 is not a uzum seller"
