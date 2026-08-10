"""Olcha category-aware sweep (Plan 5): alias mapping + tagging."""
from narxnoma.sources.olcha import CATEGORY_ALIASES, OlchaSource
from narxnoma.sources.base import Listing


def test_category_aliases_cover_all_supported_categories():
    # Verified live 2026-08-10 against /api/v2/categories leaf aliases.
    assert CATEGORY_ALIASES == {
        "smartphones": "telefony",
        "televisions": "televizory",
        "laptops": "noutbuki",
        "acs": "konditsionery",
        "fridges": "kholodilniki-i-morozilnye-kamery-1",
        "washers": "stiralnye-mashiny",
        "ovens": "plity-gazovye-i-elektricheskie",
    }


def test_sweep_tags_listings_with_the_category():
    src = OlchaSource()
    src._get_session = lambda: None
    # Stub paginate to return a smartphones-tagged listing; sweep re-tags it.
    import narxnoma.sources.olcha as mod

    def fake_paginate(fetch, parse, following):
        yield Listing(
            store_slug="olcha",
            source_key="1",
            name_raw='Телевизор Toshiba 55"',
            price=4_000_000,
            url="https://olcha.uz/x",
            category="smartphones",
        )

    mod.paginate = fake_paginate
    out = list(src.sweep(category="televisions"))
    assert len(out) == 1 and out[0].category == "televisions"


def test_sweep_rejects_unknown_category():
    src = OlchaSource()
    try:
        list(src.sweep(category="toasters"))
        assert False, "expected ValueError"
    except ValueError:
        pass