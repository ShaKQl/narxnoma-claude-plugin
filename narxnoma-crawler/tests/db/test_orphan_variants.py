"""Variants that no offer references are re-keying residue, not products."""
import pytest

from narxnoma.db import repository as repo
from narxnoma.matching.keys import VariantKey
from narxnoma.sources.base import Listing

pytestmark = pytest.mark.db


def _tv_key(code="ue55du7100uxuz"):
    return VariantKey(brand="samsung", model_tokens=frozenset({code}),
                      ram_gb=None, storage_gb=None, color=None, sim_kind=None,
                      category="televisions")


def _listing(key="tv1"):
    return Listing(store_slug="olcha", source_key=key,
                   name_raw="Телевизор Samsung UE55DU7100UXUZ", price=6_599_000,
                   url=f"https://olcha.uz/{key}", availability="IN_STOCK",
                   category="televisions")


def test_a_variant_no_offer_references_is_deleted(db_conn):
    repo.upsert_variant(db_conn, _tv_key())
    assert repo.delete_orphan_variants(db_conn) == 1
    assert repo.load_variant_keys(db_conn) == {}


def test_a_variant_with_an_offer_is_kept(db_conn):
    sid = repo.store_ids(db_conn)["olcha"]
    repo.upsert_offers(db_conn, sid, [_listing()])
    variant_id = repo.upsert_variant(db_conn, _tv_key())
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM offer WHERE source_key = 'tv1'")
        offer_id = cur.fetchone()[0]
    repo.attach_offer_to_variant(db_conn, offer_id, variant_id)

    assert repo.delete_orphan_variants(db_conn) == 0
    assert _tv_key() in repo.load_variant_keys(db_conn)


def test_an_out_of_stock_variant_is_kept(db_conn):
    # The deliberate decision recorded in schema.sql: a real product whose
    # offers have all gone out of stock keeps its page and a NULL price. Its
    # offer rows still exist, so this rule never reaches it.
    sid = repo.store_ids(db_conn)["olcha"]
    gone = Listing(store_slug="olcha", source_key="tv2",
                   name_raw="Телевизор Samsung UE55DU7100UXUZ", price=6_599_000,
                   url="https://olcha.uz/tv2", availability="OUT_OF_STOCK",
                   category="televisions")
    repo.upsert_offers(db_conn, sid, [gone])
    variant_id = repo.upsert_variant(db_conn, _tv_key())
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM offer WHERE source_key = 'tv2'")
        repo.attach_offer_to_variant(db_conn, cur.fetchone()[0], variant_id)

    assert repo.delete_orphan_variants(db_conn) == 0


def test_variant_keys_are_read_back_with_their_category(db_conn):
    # load_variant_keys omitted `category`, so every stored variant claimed to
    # be a smartphone: display_name took the phone branch and dereferenced a
    # NULL colour, and a freshly-built non-phone key could never match the one
    # loaded from the database.
    repo.upsert_variant(db_conn, _tv_key())
    keys = list(repo.load_variant_keys(db_conn))
    assert len(keys) == 1
    assert keys[0].category == "televisions"
    assert keys[0] == _tv_key()
