"""Idea category-aware sweep (Plan 5): id mapping + tagging."""
from narxnoma.sources.idea import CATEGORY_IDS, IdeaSource
from narxnoma.sources.base import Listing


def test_category_ids_cover_all_supported_categories():
    # Verified live 2026-08-10 by searching each product type.
    assert CATEGORY_IDS == {
        "smartphones": {55},
        "televisions": {9},
        "laptops": {73},
        "acs": {15},
        "fridges": {24},
        "washers": {131, 132, 23},
        "ovens": {179, 107, 17},
    }


def test_sweep_tags_listings_with_the_category():
    src = IdeaSource()
    src._fetch = lambda q: [
        Listing(store_slug="idea", source_key="1", name_raw="Televizor Samsung",
                price=4_000_000, url="https://idea.uz/x",
                category="smartphones", raw={"category_id": 9})
    ]
    out = list(src.sweep(category="televisions"))
    assert len(out) == 1 and out[0].category == "televisions"


def test_sweep_filters_by_category_id():
    src = IdeaSource()
    src._fetch = lambda q: [
        Listing(store_slug="idea", source_key="1", name_raw="Sovutgich",
                price=4_000_000, url="https://idea.uz/x", raw={"category_id": 9}),  # TV
        Listing(store_slug="idea", source_key="2", name_raw="MacBook",
                price=9_000_000, url="https://idea.uz/x", raw={"category_id": 73}),  # laptop
    ]
    out = list(src.sweep(category="televisions"))
    assert [l.source_key for l in out] == ["1"]


def test_sweep_rejects_unknown_category():
    src = IdeaSource()
    try:
        list(src.sweep(category="toasters"))
        assert False, "expected ValueError"
    except ValueError:
        pass