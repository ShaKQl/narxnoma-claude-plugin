"""Beemarket category-aware sweep (Plan 5): slug mapping + listing tagging.

The live sweep itself is verified by probe scripts (all six non-phone
categories return real, correctly-tagged products). Here we pin the
mapping and the tag logic without network access.
"""
from narxnoma.sources.beemarket import CATEGORY_SLUGS, BeemarketSource
from narxnoma.sources.base import Listing


def test_category_slugs_cover_all_supported_categories():
    # Verified live 2026-08-10 against /api/web/categories/list.
    assert CATEGORY_SLUGS == {
        "smartphones": "smartfony",
        "televisions": "televisions",
        "laptops": "laptops",
        "acs": "air-conditioners",
        "fridges": "refrigerators",
        "washers": "washing-machines",
        "ovens": "built-in-ovens",
    }


def test_sweep_tags_listings_with_the_category():
    src = BeemarketSource()
    # Stub _walk to return a smartphones-tagged listing; sweep must re-tag it.
    src._walk = lambda url, params, post_filter=None: iter(
        [
            Listing(
                store_slug="beemarket",
                source_key="1",
                name_raw="Телевизор Samsung UE55",
                price=5_000_000,
                url="https://market.beeline.uz/x",
                category="smartphones",  # parse default; sweep must override
            )
        ]
    )
    out = list(src.sweep(category="televisions"))
    assert len(out) == 1
    assert out[0].category == "televisions"


def test_sweep_rejects_unknown_category():
    src = BeemarketSource()
    try:
        list(src.sweep(category="toasters"))
        assert False, "expected ValueError"
    except ValueError:
        pass