"""idea answers a search with no results with 404, not an empty list.

Observed live: the category frontier queries "lg", which sells no phones here,
and idea returned 404. The exception escaped sweep() and cost the ENTIRE
category harvest for that source.
"""
import pytest
import requests

from narxnoma.sources.base import Listing
from narxnoma.sources.idea import IdeaSource


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=response)


def _listing():
    return Listing(
        store_slug="idea", source_key="1", name_raw="Телевизор Samsung UE55DU7100UXUZ",
        price=6_599_000, url="https://idea.uz/1", availability="IN_STOCK",
        category="televisions", raw={"category_id": 9},
    )


def test_a_barren_query_does_not_cost_the_whole_category(monkeypatch):
    calls = []

    def fake_fetch(self, query):
        calls.append(query)
        if query == "холодильник":
            raise _http_error(404)
        return [_listing()]

    monkeypatch.setattr(IdeaSource, "_fetch", fake_fetch)
    monkeypatch.setattr("narxnoma.sources.idea.CATEGORY_IDS", {"fridges": {9}})
    monkeypatch.setattr(
        "narxnoma.sources.idea.queries_for",
        lambda category: ("холодильник", "sovutgich"),
    )

    out = list(IdeaSource().sweep(category="fridges"))

    assert calls == ["холодильник", "sovutgich"], "the sweep stopped at the 404"
    assert len(out) == 1


def test_a_server_error_still_fails_loudly(monkeypatch):
    # "every query returned nothing" and "the source is down" must not look
    # the same, so only 404 is tolerated.
    monkeypatch.setattr(
        IdeaSource, "_fetch", lambda self, query: (_ for _ in ()).throw(_http_error(500))
    )
    monkeypatch.setattr("narxnoma.sources.idea.CATEGORY_IDS", {"fridges": {9}})
    monkeypatch.setattr(
        "narxnoma.sources.idea.queries_for", lambda category: ("холодильник",)
    )

    with pytest.raises(requests.HTTPError):
        list(IdeaSource().sweep(category="fridges"))
