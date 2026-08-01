import pytest

from narxnoma.db import repository as repo
from narxnoma.pipeline.report import (
    BELOW_FLOOR,
    EXPECTED_MIN_OFFERS,
    LAST_RUN_FAILED,
    MAX_OFFER_AGE_HOURS,
    NEVER_FETCHED,
    STALE,
    coverage_report,
    suspicion_reasons,
)
from narxnoma.sources.base import Listing


# --------------------------------------------------------------------------
# The three rules, each on its own, with no database. `suspicion_reasons` is
# pure precisely so a rule can be exercised without arranging a whole crawl.
# --------------------------------------------------------------------------

def test_rule_below_floor_fires_alone():
    assert suspicion_reasons(offers=3, expected_min=300, age_hours=1.0,
                             last_run_ok=True) == (BELOW_FLOOR,)


def test_rule_stale_fires_alone_even_when_the_count_clears_the_floor():
    """THE reason this rule exists.

    `offer` is upsert-only: nothing deletes or ages a row. A retailer that
    renames a category and starts returning nothing leaves yesterday's rows
    in place, so the count still clears the floor, `report` still exits 0,
    and the site serves month-old prices as current. The count rule can only
    ever catch a source that was dead on its first run against a fresh
    database -- which is exactly how the floor was verified, which is why
    this gap went unnoticed.
    """
    reasons = suspicion_reasons(offers=448, expected_min=300,
                                age_hours=MAX_OFFER_AGE_HOURS + 0.1,
                                last_run_ok=True)
    assert reasons == (STALE,)


def test_rule_last_run_failed_fires_alone():
    """last_run_ok was selected and printed but never affected the verdict."""
    assert suspicion_reasons(offers=448, expected_min=300, age_hours=1.0,
                             last_run_ok=False) == (LAST_RUN_FAILED,)


def test_no_offers_at_all_reads_as_never_fetched_not_stale():
    # Distinguishable states matter: "never fetched" and "stopped updating"
    # have different causes and different fixes.
    reasons = suspicion_reasons(offers=0, expected_min=300, age_hours=None,
                                last_run_ok=None)
    assert reasons == (BELOW_FLOOR, NEVER_FETCHED)
    assert STALE not in reasons


def test_one_missed_cycle_is_tolerated_two_are_not():
    # Harvest runs every four hours; MAX_OFFER_AGE_HOURS is a little over two
    # cycles, so a single skipped cycle must not page anyone.
    fresh = suspicion_reasons(offers=448, expected_min=300, age_hours=8.0,
                              last_run_ok=True)
    stale = suspicion_reasons(offers=448, expected_min=300, age_hours=8.9,
                              last_run_ok=True)
    assert fresh == () and stale == ()
    assert suspicion_reasons(offers=448, expected_min=300, age_hours=9.5,
                             last_run_ok=True) == (STALE,)


def test_a_healthy_source_has_no_reasons():
    assert suspicion_reasons(offers=448, expected_min=300, age_hours=0.5,
                             last_run_ok=True) == ()


@pytest.mark.parametrize("age_hours,last_run_ok", [
    (None, None),                            # never fetched
    (MAX_OFFER_AGE_HOURS * 100, False),      # ancient AND last run failed
])
def test_a_zero_floor_source_is_exempt_from_every_rule(age_hours, last_run_ok):
    """mediapark: search-only, skipped by harvest_all, no runs and no offers
    by design. A rule that fires on it is a permanent false alarm, which is
    the fastest way to teach an operator to ignore this report."""
    assert suspicion_reasons(offers=0, expected_min=0, age_hours=age_hours,
                             last_run_ok=last_run_ok) == ()


# --------------------------------------------------------------------------
# The same rules end to end, against a real database. Marked individually
# rather than with a module-level `pytestmark` so the pure tests above keep
# running on a machine with no Postgres.
# --------------------------------------------------------------------------

def _fill(conn, store_id, slug, n):
    repo.upsert_offers(conn, store_id, [
        Listing(store_slug=slug, source_key=f"k{i}", name_raw="Смартфон X",
                price=1_000_000 + i, url=f"https://{slug}.uz/k{i}")
        for i in range(n)
    ])


def _age_offers(conn, store_id, hours):
    """Backdate every offer for one store, simulating a source that stored
    rows once and then stopped refreshing them. Nothing in production ever
    writes last_seen backwards -- that is the whole point: rows only ever get
    older, and until this fix nothing looked at how old."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE offer SET last_seen = now() - make_interval(hours => %s)"
            " WHERE store_id = %s", (hours, store_id))


@pytest.mark.db
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


@pytest.mark.db
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


@pytest.mark.db
def test_source_above_floor_is_not_flagged_suspicious(db_conn):
    ids = repo.store_ids(db_conn)
    _fill(db_conn, ids["idea"], "idea", EXPECTED_MIN_OFFERS["idea"] + 10)
    rows = {r.slug: r for r in coverage_report(db_conn)}
    assert rows["idea"].is_suspicious is False
    assert rows["idea"].reasons == ()


@pytest.mark.db
def test_a_source_that_clears_its_floor_but_stopped_updating_is_flagged(db_conn):
    """The scenario this fix exists for, end to end.

    idea holds MORE offers than its floor requires, so the count rule says
    everything is fine -- and the rows have not been touched in half a day.
    Before this fix `report` exited 0 here and the site kept serving those
    prices as current.
    """
    ids = repo.store_ids(db_conn)
    _fill(db_conn, ids["idea"], "idea", EXPECTED_MIN_OFFERS["idea"] + 10)
    _age_offers(db_conn, ids["idea"], MAX_OFFER_AGE_HOURS + 3)

    row = {r.slug: r for r in coverage_report(db_conn)}["idea"]
    assert row.offers > row.expected_min       # the count rule is satisfied
    assert BELOW_FLOOR not in row.reasons
    assert row.reasons == (STALE,)
    assert row.is_suspicious is True


@pytest.mark.db
def test_a_failed_last_run_is_flagged_even_when_offers_are_fresh(db_conn):
    """last_run_ok was selected and printed but never read by the verdict."""
    ids = repo.store_ids(db_conn)
    _fill(db_conn, ids["idea"], "idea", EXPECTED_MIN_OFFERS["idea"] + 10)
    run_id = repo.start_run(db_conn, ids["idea"])
    repo.finish_run(db_conn, run_id, ok=False, seen=0, kept=0, error="upstream 503")

    row = {r.slug: r for r in coverage_report(db_conn)}["idea"]
    assert row.last_run_ok is False
    assert row.reasons == (LAST_RUN_FAILED,)


@pytest.mark.db
def test_mediapark_at_zero_offers_is_not_suspicious(db_conn):
    # mediapark's floor is 0 -- it is search-only and never swept, so zero
    # offers is its normal, healthy state, not shrinkage.
    rows = {r.slug: r for r in coverage_report(db_conn)}
    assert rows["mediapark"].offers == 0
    assert rows["mediapark"].expected_min == 0
    assert rows["mediapark"].reasons == ()
    assert rows["mediapark"].is_suspicious is False


@pytest.mark.db
def test_mediapark_is_not_flagged_by_the_freshness_or_last_run_rules_either(db_conn):
    """Widening the verdict must not start paging on the one source that is
    empty and run-less on purpose."""
    ids = repo.store_ids(db_conn)
    run_id = repo.start_run(db_conn, ids["mediapark"])
    repo.finish_run(db_conn, run_id, ok=False, seen=0, kept=0, error="boom")

    row = {r.slug: r for r in coverage_report(db_conn)}["mediapark"]
    assert row.age_hours is None and row.last_run_ok is False
    assert row.reasons == ()


@pytest.mark.db
def test_fresh_offers_report_an_age_close_to_zero(db_conn):
    # Pins that age_hours is measured against the same clock that wrote
    # last_seen -- a timezone mismatch here would silently mark every source
    # stale (or never stale) regardless of the data.
    ids = repo.store_ids(db_conn)
    _fill(db_conn, ids["olcha"], "olcha", 3)
    row = {r.slug: r for r in coverage_report(db_conn)}["olcha"]
    assert 0 <= row.age_hours < 1


@pytest.mark.db
def test_every_store_appears_even_at_zero_offers(db_conn):
    rows = {r.slug: r for r in coverage_report(db_conn)}
    assert set(rows) == set(EXPECTED_MIN_OFFERS)
