import pytest

from narxnoma.db import repository as repo
from narxnoma.pipeline.report import EXPECTED_MIN_OFFERS, coverage_report
from narxnoma.sources.base import Listing

pytestmark = pytest.mark.db


def test_coverage_report_counts_offers_per_source(db_conn):
    ids = repo.store_ids(db_conn)
    repo.upsert_offers(db_conn, ids["olcha"], [
        Listing(store_slug="olcha", source_key=f"k{i}", name_raw="Смартфон X",
                price=1_000_000 + i, url=f"https://olcha.uz/k{i}")
        for i in range(3)
    ])
    rows = {r.slug: r for r in coverage_report(db_conn)}
    assert rows["olcha"].offers == 3
    assert rows["idea"].offers == 0          # every store appears, even at zero
    assert rows["olcha"].newest_seen is not None


def test_source_below_floor_is_flagged_suspicious(db_conn):
    ids = repo.store_ids(db_conn)
    # olcha's floor is 300; 3 offers is far below it.
    repo.upsert_offers(db_conn, ids["olcha"], [
        Listing(store_slug="olcha", source_key=f"k{i}", name_raw="Смартфон X",
                price=1_000_000 + i, url=f"https://olcha.uz/k{i}")
        for i in range(3)
    ])
    rows = {r.slug: r for r in coverage_report(db_conn)}
    assert rows["olcha"].is_suspicious is True


def test_source_above_floor_is_not_flagged_suspicious(db_conn):
    ids = repo.store_ids(db_conn)
    floor = EXPECTED_MIN_OFFERS["idea"]
    repo.upsert_offers(db_conn, ids["idea"], [
        Listing(store_slug="idea", source_key=f"k{i}", name_raw="Смартфон X",
                price=1_000_000 + i, url=f"https://idea.uz/k{i}")
        for i in range(floor + 10)
    ])
    rows = {r.slug: r for r in coverage_report(db_conn)}
    assert rows["idea"].is_suspicious is False


def test_mediapark_at_zero_offers_is_not_suspicious(db_conn):
    # mediapark's floor is 0 -- it is search-only and never swept, so zero
    # offers is its normal, healthy state, not shrinkage.
    rows = {r.slug: r for r in coverage_report(db_conn)}
    assert rows["mediapark"].offers == 0
    assert rows["mediapark"].expected_min == 0
    assert rows["mediapark"].is_suspicious is False


def test_every_store_appears_even_at_zero_offers(db_conn):
    rows = {r.slug: r for r in coverage_report(db_conn)}
    assert set(rows) == set(EXPECTED_MIN_OFFERS)
