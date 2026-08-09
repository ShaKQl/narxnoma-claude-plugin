"""The shared pagination loop. Six clients hand-rolled this; none retried."""
import pytest

from narxnoma.sources.base import Listing, paginate


def listing(key: str) -> Listing:
    return Listing(store_slug="test", source_key=key, name_raw=f"Phone {key}",
                   price=1_000_000, url=f"https://example.test/{key}",
                   availability="IN_STOCK")


def pages(*payloads):
    """A fetch_page over a fixed list of payloads, recording the calls made."""
    calls = []

    def fetch(page):
        calls.append(page)
        return payloads[page - 1]

    return fetch, calls


def parse_page(payload):
    return [listing(k) for k in payload["keys"]]


def next_page(payload, page):
    return page + 1 if page < payload["last"] else None


def test_walks_every_page_to_the_end():
    fetch, calls = pages({"keys": ["a", "b"], "last": 3},
                         {"keys": ["c"], "last": 3},
                         {"keys": ["d"], "last": 3})
    got = [x.source_key for x in paginate(fetch, parse_page, next_page)]
    assert got == ["a", "b", "c", "d"]
    assert calls == [1, 2, 3]


def test_a_transient_page_failure_is_retried_not_fatal():
    # THE BUG THIS EXISTS FOR: a beemarket 502 on one page lost that source's
    # entire cycle. A retry minutes later succeeded, so the failure really was
    # transient -- the sweep simply had no way to survive it.
    attempts = {"n": 0}

    def fetch(page):
        if page == 2:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise OSError("502 Bad Gateway")
        return {"keys": [f"p{page}"], "last": 3}

    got = [x.source_key for x in paginate(fetch, parse_page, next_page)]
    assert got == ["p1", "p2", "p3"]
    assert attempts["n"] == 2, "the failing page must be retried, not skipped"


def test_a_page_that_keeps_failing_raises_after_its_retries():
    # Retrying forever would hammer a retailer that is genuinely down. The
    # error must surface so harvest_run records ok=false and the coverage
    # report flags the source.
    def fetch(page):
        if page == 2:
            raise OSError("503 Service Unavailable")
        return {"keys": [f"p{page}"], "last": 3}

    with pytest.raises(OSError, match="503"):
        list(paginate(fetch, parse_page, next_page, retries=2))


def test_pages_already_yielded_survive_a_later_failure():
    # harvest_source writes in batches as the sweep proceeds, so everything
    # yielded before the failure is already durable. The generator must not
    # discard it -- that is why the retry sits INSIDE the loop rather than
    # around the whole sweep.
    def fetch(page):
        if page == 3:
            raise OSError("boom")
        return {"keys": [f"p{page}"], "last": 5}

    got = []
    with pytest.raises(OSError):
        for item in paginate(fetch, parse_page, next_page, retries=0):
            got.append(item.source_key)
    assert got == ["p1", "p2"]


def test_max_pages_stops_a_runaway_paginator():
    # A retailer whose last_page grows every request, or a next_page that
    # never returns None, would otherwise loop until the cron killed it.
    def fetch(page):
        return {"keys": [f"p{page}"], "last": 10_000}

    got = list(paginate(fetch, parse_page, next_page, max_pages=5))
    assert len(got) == 5


def test_next_page_is_the_sole_authority_on_stopping():
    """A page that PARSES to nothing must NOT end the sweep.

    Found in pre-flight. The obvious design -- stop when parse_page returns
    an empty list -- silently changes every client's behaviour: a page whose
    items are all dropped by the price fence or a category filter would end
    the sweep and lose every following page. texnomart's own fixture already
    drops an item below the fence, and Task 3 adds a filter that can empty a
    whole page of accessories.

    Only next_page decides. A client that wants an empty payload to stop --
    uzum, whose offset pagination has no last_page to compare -- says so by
    returning None from its own next_page.
    """
    fetch, calls = pages({"keys": [], "last": 3},
                         {"keys": ["b"], "last": 3},
                         {"keys": ["c"], "last": 3})
    got = [x.source_key for x in paginate(fetch, parse_page, next_page)]
    assert got == ["b", "c"], "an empty page must not truncate the sweep"
    assert calls == [1, 2, 3]


def test_a_client_can_still_stop_on_an_empty_payload():
    # uzum paginates by offset with no last_page, so an empty payload IS its
    # end signal -- expressed in its own next_page, not assumed by the loop.
    def stop_when_empty(payload, page):
        return page + 1 if payload["keys"] else None

    fetch, calls = pages({"keys": ["a"], "last": 9}, {"keys": [], "last": 9})
    got = [x.source_key for x in paginate(fetch, parse_page, stop_when_empty)]
    assert got == ["a"]
    assert calls == [1, 2]


def test_retry_pauses_between_attempts(monkeypatch):
    # Retrying a struggling API at full speed is the opposite of backing off.
    slept = []
    monkeypatch.setattr("narxnoma.sources.base.pause", lambda: slept.append(1))

    def fetch(page):
        if page == 1 and not slept:
            raise OSError("transient")
        return {"keys": ["a"], "last": 1}

    list(paginate(fetch, parse_page, next_page))
    assert slept, "a retry must pause before trying again"
