"""Clustering: attach only when exactly one product can be the right one."""
import pytest

from narxnoma.db import repository as repo
from narxnoma.pipeline.cluster import (
    REASON_AMBIGUOUS,
    REASON_NO_CANDIDATE,
    REASON_MEMORY_IN_MODEL,
    REASON_NO_IDENTITY,
    cluster_offers,
    detach_drifted_offers,
)
from narxnoma.pipeline.extract import identify
from narxnoma.sources.base import Listing

pytestmark = pytest.mark.db


def seed_offer(conn, name, key="k1", store="olcha", price=2_723_000):
    """Put one real offer row in the database and return its id."""
    ids = repo.store_ids(conn)
    repo.upsert_offers(conn, ids[store], [Listing(
        store_slug=store, source_key=key, name_raw=name, price=price,
        url=f"https://{store}.uz/{key}", availability="IN_STOCK")])
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM offer WHERE source_key = %s AND store_id = %s",
                    (key, ids[store]))
        return cur.fetchone()[0]


def identities_for(conn):
    return [identify(row) for row in repo.load_unattached_offers(conn)]


def variant_count(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM variant")
        return cur.fetchone()[0]


def unresolved_reason(conn, offer_id):
    with conn.cursor() as cur:
        cur.execute("SELECT reason FROM unresolved_offer WHERE offer_id = %s", (offer_id,))
        row = cur.fetchone()
        return row[0] if row else None


def attached_variant(conn, offer_id):
    with conn.cursor() as cur:
        cur.execute("SELECT variant_id FROM offer WHERE id = %s", (offer_id,))
        return cur.fetchone()[0]


def test_differing_case_and_wording_collapse_to_one_variant(db_conn):
    # "Cosmic orange" and "Cosmic Orange" are two separate products on a
    # competitor's site, splitting the offer pool so BOTH pages show a wrong
    # minimum. The canonical key is case- and wording-insensitive by
    # construction, so this must be impossible here.
    a = seed_offer(db_conn, "Смартфон Apple iPhone 17 Pro Max 256 ГБ, Cosmic orange", "a1")
    b = seed_offer(db_conn, "iPhone 17 Pro Max 256GB Cosmic Orange", "b1", store="idea")

    result = cluster_offers(db_conn, identities_for(db_conn))

    assert result.attached == 2
    assert variant_count(db_conn) == 1
    assert attached_variant(db_conn, a) == attached_variant(db_conn, b)


def test_ambiguous_partial_is_parked_not_guessed(db_conn):
    # Both 8/256 and 12/256 exist. An offer stating only 256 is compatible with
    # both, so no evidence picks one. Attaching it anyway -- which produces a
    # fuller-looking catalogue -- is the exact defect this platform exists to
    # avoid, because the price would then be shown against a phone it is not for.
    seed_offer(db_conn, "Смартфон Xiaomi Redmi Note 15 8/256 ГБ, чёрный", "full8")
    seed_offer(db_conn, "Смартфон Xiaomi Redmi Note 15 12/256 ГБ, чёрный", "full12")
    ambiguous = seed_offer(db_conn, "Смартфон Xiaomi Redmi Note 15 256 ГБ, чёрный", "amb")

    result = cluster_offers(db_conn, identities_for(db_conn))

    assert attached_variant(db_conn, ambiguous) is None
    assert unresolved_reason(db_conn, ambiguous) == REASON_AMBIGUOUS
    assert result.unresolved == 1
    with db_conn.cursor() as cur:
        cur.execute("SELECT candidate_ids FROM unresolved_offer WHERE offer_id = %s",
                    (ambiguous,))
        assert len(cur.fetchone()[0]) == 2, "both candidates must be recorded"


def test_partial_with_exactly_one_candidate_attaches(db_conn):
    # Only 8/256 exists, so "256" can only mean that one. Evidence, not a guess.
    full = seed_offer(db_conn, "Смартфон Xiaomi Redmi Note 15 8/256 ГБ, чёрный", "full8")
    partial = seed_offer(db_conn, "Смартфон Xiaomi Redmi Note 15 256 ГБ, чёрный", "part")

    cluster_offers(db_conn, identities_for(db_conn))

    assert attached_variant(db_conn, partial) is not None
    assert attached_variant(db_conn, partial) == attached_variant(db_conn, full)
    assert unresolved_reason(db_conn, partial) is None


def test_partial_with_no_candidate_is_parked_distinctly(db_conn):
    # Nothing to attach to. Different from ambiguity, and the report must be
    # able to tell them apart: this is a catalogue gap, not a vague listing.
    orphan = seed_offer(db_conn, "Смартфон Vivo Y31d 256 ГБ, чёрный", "orph")

    cluster_offers(db_conn, identities_for(db_conn))

    assert attached_variant(db_conn, orphan) is None
    assert unresolved_reason(db_conn, orphan) == REASON_NO_CANDIDATE


def test_no_identity_at_all_is_parked(db_conn):
    # A catalogue parent with no variant spec: real, and common.
    vague = seed_offer(db_conn, "Смартфон Honor X5d Plus", "vague")

    cluster_offers(db_conn, identities_for(db_conn))

    assert attached_variant(db_conn, vague) is None
    assert unresolved_reason(db_conn, vague) == REASON_NO_IDENTITY


def test_esim_only_and_dual_are_different_variants(db_conn):
    # An eSIM-only iPhone is a different product at a materially different
    # price -- one marketplace lists them side by side at 18.1M and 20.8M.
    seed_offer(db_conn, "Смартфон Apple iPhone 17 Pro 256 ГБ (nanoSim+eSim), Silver", "dual")
    seed_offer(db_conn, "Смартфон Apple iPhone 17 Pro 256 ГБ (eSIM), Silver", "esim")

    cluster_offers(db_conn, identities_for(db_conn))

    assert variant_count(db_conn) == 2


def test_clustering_is_idempotent(db_conn):
    seed_offer(db_conn, "Смартфон Honor X9d 12/256 ГБ, черный", "h1")
    seed_offer(db_conn, "Honor X9d 12/256 GB Midnight Black", "h2", store="idea")

    first = cluster_offers(db_conn, identities_for(db_conn))
    after_first = variant_count(db_conn)
    second = cluster_offers(db_conn, identities_for(db_conn))

    assert first.attached == 2
    assert after_first == 1
    assert variant_count(db_conn) == 1, "a second run must not duplicate variants"
    assert second.attached == 0, "already-attached offers are not reconsidered"


def test_a_parked_offer_is_retried_and_attaches_once_its_variant_exists(db_conn):
    # THE RETRY RULE, in the shape it actually takes in production. A vague
    # listing arrives before any retailer has published a fully-specified one,
    # so there is nothing to attach it to. Cycles later another retailer lists
    # the same phone properly, and the earlier offer becomes resolvable.
    #
    # Without the retry, that offer is dead the moment it is first parked, and
    # the unresolved count becomes a permanently rising number nobody can act
    # on -- when it is supposed to be the signal that the matcher needs work.
    partial = seed_offer(db_conn, "Смартфон Xiaomi Redmi Note 15 256 ГБ, чёрный", "part")

    cluster_offers(db_conn, identities_for(db_conn))
    assert unresolved_reason(db_conn, partial) == REASON_NO_CANDIDATE
    assert variant_count(db_conn) == 0

    # A later cycle: another retailer publishes the full specification.
    seed_offer(db_conn, "Смартфон Xiaomi Redmi Note 15 8/256 ГБ, чёрный",
               "full8", store="idea")

    cluster_offers(db_conn, identities_for(db_conn))

    assert attached_variant(db_conn, partial) is not None
    assert unresolved_reason(db_conn, partial) is None, \
        "the refusal must be cleared once the offer attaches"


def test_a_parked_offer_stays_parked_while_it_remains_ambiguous(db_conn):
    # The retry must not become a slow leak into guessing: reconsidering an
    # offer every cycle is only safe because the answer is still "refuse" until
    # the evidence actually changes.
    seed_offer(db_conn, "Смартфон Xiaomi Redmi Note 15 8/256 ГБ, чёрный", "full8")
    seed_offer(db_conn, "Смартфон Xiaomi Redmi Note 15 12/256 ГБ, чёрный", "full12")
    ambiguous = seed_offer(db_conn, "Смартфон Xiaomi Redmi Note 15 256 ГБ, чёрный", "amb")

    for _ in range(3):
        cluster_offers(db_conn, identities_for(db_conn))
        assert attached_variant(db_conn, ambiguous) is None
        assert unresolved_reason(db_conn, ambiguous) == REASON_AMBIGUOUS


def test_display_name_is_generated_not_copied(db_conn):
    # Copying a retailer's wording is how a competitor ended up with two
    # products for one phone. The name is a function of the key.
    seed_offer(db_conn, "HONOR   x9d  12/256gb   midnight black", "h1")

    cluster_offers(db_conn, identities_for(db_conn))

    with db_conn.cursor() as cur:
        cur.execute("SELECT display_name, slug FROM variant")
        name, slug_value = cur.fetchone()
    assert name == "Смартфон Honor X9D 12/256 ГБ, Черный"
    assert slug_value == "honor-x9d-12-256-black"


def test_a_memory_figure_in_the_model_tokens_is_refused_not_catalogued(db_conn):
    """No phone is named "256". A capacity that reached the model tokens is
    always a parsing failure, so the variant it would mint is a product that
    does not exist -- and minting it pools genuinely different SKUs behind
    one headline price, which is the exact defect this platform exists to
    avoid, reproduced in our own data.

    This is a backstop, not the repair. The uzum card-range leak that made
    it necessary is fixed at source; the guard stays because the failure is
    silent by construction -- a wrong variant looks exactly like a right one
    -- and any source can reintroduce it.
    """
    offer_id = seed_offer(
        db_conn, "Смартфон Apple iPhone 17 256 Pro Max 512 ГБ, Оранжевый", "leak")

    result = cluster_offers(db_conn, identities_for(db_conn))

    assert result.attached == 0
    assert variant_count(db_conn) == 0
    assert unresolved_reason(db_conn, offer_id) == REASON_MEMORY_IN_MODEL


def test_a_real_model_number_is_not_mistaken_for_a_capacity(db_conn):
    """The guard keys on capacities only. Model numbers that merely look
    numeric -- 12, 15, 17, 200 -- must still catalogue normally.
    """
    seed_offer(db_conn, "Смартфон Apple iPhone 12 Pro 256 ГБ, Черный", "ok1")
    seed_offer(db_conn, "Смартфон Honor 200 Pro 12/512 ГБ, Черный", "ok2", store="idea")

    result = cluster_offers(db_conn, identities_for(db_conn))

    assert result.attached == 2
    assert variant_count(db_conn) == 2


def test_an_offer_whose_name_now_says_something_else_is_re_examined(db_conn):
    """A parser fix must be able to heal the catalogue it already wrote.

    Clustering only ever loads offers with variant_id IS NULL, so an offer
    attached in an earlier cycle is never reconsidered. That is right while
    name_raw is stable -- and wrong the moment a source fix changes it,
    which is exactly when the catalogue is most likely to be wrong. The
    uzum card-range repair rewrote 217 stored names; without this the
    offers behind them would have sat on their old, incorrect variants
    indefinitely, and no report would have said so.
    """
    offer_id = seed_offer(db_conn, "Смартфон Honor X9d 12/256 ГБ, черный", "drift")
    cluster_offers(db_conn, identities_for(db_conn))
    original = attached_variant(db_conn, offer_id)
    assert original is not None

    # The source is corrected and the next harvest stores a different name.
    with db_conn.cursor() as cur:
        cur.execute("UPDATE offer SET name_raw = %s WHERE id = %s",
                    ("Смартфон Honor X9d 12/512 ГБ, черный", offer_id))

    detached = detach_drifted_offers(db_conn)
    assert detached == 1
    cluster_offers(db_conn, identities_for(db_conn))

    moved = attached_variant(db_conn, offer_id)
    assert moved is not None and moved != original
    with db_conn.cursor() as cur:
        cur.execute("SELECT storage_gb FROM variant WHERE id = %s", (moved,))
        assert cur.fetchone()[0] == 512


def test_an_unchanged_catalogue_detaches_nothing(db_conn):
    """Reconciliation runs every cycle, so a steady state must be a no-op --
    otherwise it churns every offer through detach and re-attach each run.
    """
    seed_offer(db_conn, "Смартфон Honor X9d 12/256 ГБ, черный", "a")
    seed_offer(db_conn, "Смартфон Apple iPhone 17 Pro 256 ГБ, Синий", "b", store="idea")
    cluster_offers(db_conn, identities_for(db_conn))

    assert detach_drifted_offers(db_conn) == 0
    assert detach_drifted_offers(db_conn) == 0


def test_a_partial_attachment_compatible_with_its_variant_is_left_alone(db_conn):
    """An offer attached by partial resolution has no full key of its own, so
    "re-derive and compare" cannot judge it. It is kept while it remains
    COMPATIBLE with the variant it sits on, and only detached when the name
    now contradicts it -- otherwise every cycle would tear down and rebuild
    every partial attachment.
    """
    seed_offer(db_conn, "Смартфон Honor X9d 12/256 ГБ, черный", "full")
    partial = seed_offer(db_conn, "Honor X9d 256 ГБ черный", "part", store="idea")
    cluster_offers(db_conn, identities_for(db_conn))
    assert attached_variant(db_conn, partial) is not None

    assert detach_drifted_offers(db_conn) == 0


def test_display_names_are_regenerated_not_frozen_at_creation(db_conn):
    """upsert_variant uses ON CONFLICT DO NOTHING, so a variant's name is
    written once and never revisited. A correction to the generator would
    then apply only to products first seen afterwards and leave the existing
    catalogue on the old wording -- the same shape as the schema.sql header
    rule, where a change silently applies to fresh data but not production.
    """
    seed_offer(db_conn, "Смартфон Honor X9d 12/256 ГБ, черный", "n1")
    cluster_offers(db_conn, identities_for(db_conn))

    with db_conn.cursor() as cur:
        cur.execute("UPDATE variant SET display_name = 'stale wording'")
    assert repo.refresh_display_names(db_conn) == 1

    with db_conn.cursor() as cur:
        cur.execute("SELECT display_name FROM variant")
        assert cur.fetchone()[0] == "Смартфон Honor X9D 12/256 ГБ, Черный"

    # Idempotent: a catalogue already correct must report no changes.
    assert repo.refresh_display_names(db_conn) == 0
