import pytest

from narxnoma.pipeline.harvest import WRITE_BATCH_SIZE, HarvestResult, harvest_all
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
        # One entry per record_raw_offers/upsert_offers call, holding the
        # batch size written that call -- lets tests assert *how many
        # writes* happened, not just the eventual totals.
        self.raw_batches, self.upsert_batches = [], []

    def store_ids(self, conn):
        return {"olcha": "sid-olcha", "idea": "sid-idea"}

    def record_raw_offers(self, conn, store_id, listings):
        listings = list(listings)
        self.raw.extend(listings)
        self.raw_batches.append(len(listings))
        return len(listings)

    def upsert_offers(self, conn, store_id, listings):
        listings = list(listings)
        self.upserts.extend(listings)
        self.upsert_batches.append(len(listings))
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
    # Fix 1: a skip must carry its own flag rather than being indistinguishable
    # from a real, successful, zero-listing run.
    assert results[0].skipped is True


class FlakyStartRunRepo(FakeRepo):
    """start_run raises the first time it's called (simulating a transient
    DB hiccup), then behaves normally for every source after that."""

    def __init__(self):
        super().__init__()
        self._calls = 0

    def start_run(self, conn, store_id):
        self._calls += 1
        if self._calls == 1:
            raise RuntimeError("db connection reset")
        return super().start_run(conn, store_id)


def test_start_run_failure_does_not_abort_the_cycle():
    # Fix 2: start_run is not inside the old try block, so a bare DB hiccup
    # there used to propagate out of harvest_all and abort every source
    # queued behind the failing one. It must not.
    repo = FlakyStartRunRepo()
    bad = FakeSource([a_listing("a")])
    bad.slug = "idea"
    good = FakeSource([a_listing("b")])
    results = harvest_all(conn=None, sources=[bad, good], repo=repo)
    by_slug = {r.slug: r for r in results}
    assert by_slug["idea"].ok is False
    assert "db connection reset" in by_slug["idea"].error
    assert by_slug["olcha"].ok is True           # the good source still ran
    assert len(repo.upserts) == 1


class FinishRunAlwaysBoomsRepo(FakeRepo):
    def finish_run(self, conn, run_id, ok, seen, kept, error=None):
        raise RuntimeError("db gone while recording the failure")


def test_finish_run_failure_is_swallowed_not_raised():
    # Fix 2: if finish_run itself fails while recording a failure,
    # harvest_source must log it and still return a failed HarvestResult
    # rather than letting that second exception escape.
    repo = FinishRunAlwaysBoomsRepo()
    bad = FakeSource(boom=True)
    results = harvest_all(conn=None, sources=[bad], repo=repo)
    assert results[0].ok is False
    assert "503" in results[0].error


def test_large_sweep_is_written_in_batches():
    # Fix 3: buffering the whole sweep before writing anything loses
    # everything already fetched if the sweep dies partway through. Writing
    # WRITE_BATCH_SIZE-sized chunks as the sweep proceeds fixes that -- this
    # test just pins that more than one write happens and the totals add up.
    repo = FakeRepo()
    total = WRITE_BATCH_SIZE * 2 + 200
    listings = [a_listing(f"item-{i}") for i in range(total)]
    results = harvest_all(conn=None, sources=[FakeSource(listings)], repo=repo)

    assert results[0].ok is True
    assert results[0].kept == total
    assert results[0].seen == total
    assert len(repo.raw) == total
    assert len(repo.upserts) == total
    assert repo.raw_batches == [WRITE_BATCH_SIZE, WRITE_BATCH_SIZE, 200]
    assert repo.upsert_batches == [WRITE_BATCH_SIZE, WRITE_BATCH_SIZE, 200]


class PartialSweepThenBoomSource:
    """Yields one full batch's worth of listings, then blows up before the
    sweep completes -- simulating an upstream failure partway through a
    large catalogue."""

    slug = "olcha"
    can_sweep = True

    def sweep(self):
        for i in range(WRITE_BATCH_SIZE + 100):
            yield a_listing(f"item-{i}")
        raise RuntimeError("upstream 503 mid-sweep")

    def search(self, query):
        return iter(())


def test_partial_sweep_keeps_the_batch_already_flushed():
    # Fix 3: the first full WRITE_BATCH_SIZE-sized batch must already be
    # written by the time the source raises, even though the sweep never
    # finishes and the run is recorded as failed overall.
    repo = FakeRepo()
    results = harvest_all(conn=None, sources=[PartialSweepThenBoomSource()], repo=repo)

    assert results[0].ok is False
    assert "503" in results[0].error
    assert len(repo.raw) == WRITE_BATCH_SIZE
    assert len(repo.upserts) == WRITE_BATCH_SIZE
    assert repo.runs[0]["ok"] is False
