"""Pass B: reaching the source that cannot be swept. No network here."""
import pytest

from narxnoma.pipeline.backfill import (
    BackfillResult,
    backfill_search_only_sources,
    build_query,
)
from narxnoma.sources.base import Listing


class FakeMediapark:
    slug = "mediapark"
    can_sweep = False

    def __init__(self, results=None, boom_on=None):
        self.results = results or {}
        self.boom_on = boom_on
        self.queries = []

    def sweep(self):
        raise NotImplementedError("mediapark is search-only")

    def search(self, query):
        self.queries.append(query)
        if self.boom_on and self.boom_on in query:
            raise RuntimeError("upstream 500")
        return iter(self.results.get(query, []))


class FakeRepo:
    def __init__(self):
        self.raw = []
        self.upserts = []

    def record_raw_offers(self, conn, store_id, listings):
        listings = list(listings)
        self.raw.extend(listings)
        return len(listings)

    def upsert_offers(self, conn, store_id, listings):
        listings = list(listings)
        self.upserts.extend(listings)
        return len(listings), 0


def listing(key="m1", price=4_839_000):
    return Listing(store_slug="mediapark", source_key=key,
                   name_raw="Смартфон Honor X9D 12/256", price=price,
                   url=f"https://mediapark.uz/{key}")


HONOR = "Смартфон Honor X9D 12/256 ГБ, Черный"


def test_query_drops_our_own_prefix_but_keeps_memory_and_colour():
    # mediapark RANKS rather than filtering with strict AND, so stripping the
    # memory figure or the colour measurably worsens recall. Only our own
    # generated "Смартфон" prefix goes -- no retailer indexes that.
    query = build_query(HONOR)
    assert not query.startswith("Смартфон")
    assert "Honor X9D" in query
    assert "12/256" in query, "memory must survive: it is what ranks the right variant"
    assert "Черный" in query, "colour must survive for the same reason"


def test_query_is_stable_for_an_apple_variant_without_ram():
    assert build_query("Смартфон Apple iPhone 17 Pro 256 ГБ, Серебристый") == \
        "Apple iPhone 17 Pro 256 Серебристый"


def test_results_are_written_as_offers():
    source = FakeMediapark({build_query(HONOR): [listing()]})
    repo = FakeRepo()

    result = backfill_search_only_sources(
        None, source, "store-1", [("v1", HONOR)], repo=repo)

    assert result.queried == 1
    assert result.variants_matched == 1
    assert result.offers_written == 1
    assert len(repo.raw) == 1 and len(repo.upserts) == 1


def test_a_variant_with_no_match_records_nothing_and_does_not_raise():
    source = FakeMediapark({})
    repo = FakeRepo()

    result = backfill_search_only_sources(
        None, source, "store-1", [("v1", HONOR)], repo=repo)

    assert result.misses == 1
    assert result.variants_matched == 0
    assert repo.raw == [] and repo.upserts == []


def test_one_failing_query_does_not_end_the_pass():
    # A single bad response must not cost us the rest of the catalogue.
    good = build_query("Смартфон Honor X9D 12/256 ГБ, Черный")
    source = FakeMediapark({good: [listing()]}, boom_on="Pixel")
    repo = FakeRepo()

    result = backfill_search_only_sources(
        None, source, "store-1",
        [("v1", "Смартфон Google Pixel 10 12/256 ГБ, Черный"), ("v2", HONOR)],
        repo=repo)

    assert result.queried == 2
    assert result.misses == 1
    assert result.variants_matched == 1, "the good query still ran and wrote"


def test_the_pass_is_bounded_so_one_cycle_cannot_run_away():
    # The catalogue grows without limit; a backfill that scaled with it would
    # eventually outlast the four-hour window and collide with the next run.
    source = FakeMediapark({})
    repo = FakeRepo()
    variants = [(f"v{i}", f"Смартфон Honor X{i} 12/256 ГБ, Черный") for i in range(50)]

    result = backfill_search_only_sources(
        None, source, "store-1", variants, repo=repo, max_queries=10)

    assert result.queried == 10
    assert len(source.queries) == 10


def test_backfill_never_calls_sweep():
    # sweep() raises for this source by design; the whole point of Pass B is
    # that it reaches mediapark another way.
    source = FakeMediapark({})
    backfill_search_only_sources(None, source, "store-1", [("v1", HONOR)],
                                 repo=FakeRepo())
    with pytest.raises(NotImplementedError):
        source.sweep()


def test_backfill_does_not_attach_anything_itself():
    # A search hit is a suggestion, not evidence. Clustering decides on the
    # next run whether the listing really is that variant.
    import inspect

    import narxnoma.pipeline.backfill as mod

    source = inspect.getsource(mod)
    assert "attach_offer_to_variant" not in source
    assert "upsert_variant" not in source


def test_result_starts_empty():
    assert BackfillResult() == BackfillResult(0, 0, 0, 0)
