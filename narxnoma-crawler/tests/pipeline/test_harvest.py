import pytest

from narxnoma.pipeline.harvest import HarvestResult, harvest_all
from narxnoma.sources.base import Listing


class FakeSource:
    slug = "olcha"
    can_sweep = True

    def __init__(self, listings=None, boom=False):
        self._listings = listings or []
        self._boom = boom

    def sweep(self):
        if self._boom:
            raise RuntimeError("upstream 503")
        yield from self._listings

    def search(self, query):
        return iter(())


class FakeRepo:
    def __init__(self):
        self.raw, self.upserts, self.runs = [], [], []

    def store_ids(self, conn):
        return {"olcha": "sid-olcha", "idea": "sid-idea"}

    def record_raw_offers(self, conn, store_id, listings):
        listings = list(listings)
        self.raw.extend(listings)
        return len(listings)

    def upsert_offers(self, conn, store_id, listings):
        listings = list(listings)
        self.upserts.extend(listings)
        return len(listings), 0

    def start_run(self, conn, store_id):
        self.runs.append({"store": store_id})
        return len(self.runs)

    def finish_run(self, conn, run_id, ok, seen, kept, error=None):
        self.runs[run_id - 1].update(ok=ok, seen=seen, kept=kept, error=error)


def a_listing(key):
    return Listing(store_slug="olcha", source_key=key, name_raw="Смартфон X",
                   price=1_500_000, url=f"https://olcha.uz/{key}")


def test_harvest_writes_raw_and_offers():
    repo = FakeRepo()
    results = harvest_all(conn=None, sources=[FakeSource([a_listing("a"), a_listing("b")])],
                          repo=repo)
    assert [r.ok for r in results] == [True]
    assert results[0].kept == 2
    assert len(repo.raw) == 2 and len(repo.upserts) == 2


def test_one_failing_source_does_not_abort_the_cycle():
    repo = FakeRepo()
    good = FakeSource([a_listing("a")])
    bad = FakeSource(boom=True)
    bad.slug = "idea"
    results = harvest_all(conn=None, sources=[bad, good], repo=repo)
    by_slug = {r.slug: r for r in results}
    assert by_slug["idea"].ok is False
    assert "503" in by_slug["idea"].error
    assert by_slug["olcha"].ok is True          # the good source still ran
    assert len(repo.upserts) == 1


def test_failure_is_recorded_against_the_run():
    repo = FakeRepo()
    bad = FakeSource(boom=True)
    harvest_all(conn=None, sources=[bad], repo=repo)
    assert repo.runs[0]["ok"] is False
    assert repo.runs[0]["error"]


class RaisingSweepSource:
    """Pins the can_sweep contract: harvest_all must check can_sweep and
    skip this source *before* ever calling sweep(). If a future change
    "simplifies" that check into a try/except around sweep(), this test
    fails because sweep() raises AssertionError the moment it's called."""

    slug = "mediapark"
    can_sweep = False

    def sweep(self):
        raise AssertionError("sweep() must not be called when can_sweep is False")

    def search(self, query):
        return iter(())


def test_can_sweep_false_is_skipped_not_caught():
    repo = FakeRepo()
    source = RaisingSweepSource()
    results = harvest_all(conn=None, sources=[source], repo=repo)
    assert results[0].slug == "mediapark"
    assert results[0].ok is True
    assert results[0].kept == 0
    # No run was started or finished for a skipped source.
    assert repo.runs == []
