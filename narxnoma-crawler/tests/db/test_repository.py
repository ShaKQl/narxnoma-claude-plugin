import pytest

from narxnoma.db import repository as repo
from narxnoma.sources.base import Listing

pytestmark = pytest.mark.db


def listing(key="k1", price=2_723_000, name="Смартфон Xiaomi Redmi Note 15 8/256 ГБ, Синий"):
    return Listing(store_slug="olcha", source_key=key, name_raw=name,
                   price=price, url=f"https://olcha.uz/{key}", availability="IN_STOCK")


def test_store_ids_returns_all_seeded_stores(db_conn):
    ids = repo.store_ids(db_conn)
    assert set(ids) == {"uzum", "alifshop", "beemarket", "idea", "mediapark",
                        "olcha", "texnomart", "asaxiy", "radius", "glotr", "openshop"}


def test_raw_offer_is_append_only(db_conn):
    sid = repo.store_ids(db_conn)["olcha"]
    repo.record_raw_offers(db_conn, sid, [listing(price=2_723_000)])
    repo.record_raw_offers(db_conn, sid, [listing(price=2_699_000)])
    with db_conn.cursor() as cur:
        # ORDER BY id, not observed_at: observed_at defaults to now(), which is the
        # transaction timestamp -- rows written in the same transaction share it, so
        # only id (true insertion order) disambiguates them.
        cur.execute("SELECT price FROM raw_offer WHERE source_key='k1' ORDER BY id")
        assert [r[0] for r in cur.fetchall()] == [2_723_000, 2_699_000]


def test_upsert_inserts_then_updates_keeping_first_seen(db_conn):
    sid = repo.store_ids(db_conn)["olcha"]
    assert repo.upsert_offers(db_conn, sid, [listing(price=2_723_000)]) == (1, 0)
    with db_conn.cursor() as cur:
        cur.execute("SELECT first_seen FROM offer WHERE source_key='k1'")
        first = cur.fetchone()[0]

    assert repo.upsert_offers(db_conn, sid, [listing(price=2_699_000)]) == (0, 1)
    with db_conn.cursor() as cur:
        cur.execute("SELECT price, first_seen, last_seen FROM offer WHERE source_key='k1'")
        price, first_seen, last_seen = cur.fetchone()
    assert price == 2_699_000
    assert first_seen == first          # first_seen must never move
    assert last_seen >= first_seen


def test_upsert_does_not_duplicate_on_rerun(db_conn):
    sid = repo.store_ids(db_conn)["olcha"]
    repo.upsert_offers(db_conn, sid, [listing()])
    repo.upsert_offers(db_conn, sid, [listing()])
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM offer WHERE source_key='k1'")
        assert cur.fetchone()[0] == 1


def test_run_bookkeeping(db_conn):
    sid = repo.store_ids(db_conn)["olcha"]
    run_id = repo.start_run(db_conn, sid)
    repo.finish_run(db_conn, run_id, ok=True, seen=440, kept=438)
    with db_conn.cursor() as cur:
        cur.execute("SELECT ok, listings_seen, listings_kept, finished_at IS NOT NULL"
                    " FROM harvest_run WHERE id=%s", (run_id,))
        assert cur.fetchone() == (True, 440, 438, True)
