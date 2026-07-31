import pytest

from narxnoma.sources.base import (
    PRICE_MAX, PRICE_MIN, Listing, is_plausible_price,
)


def test_price_fences():
    # A tiyin/SUM confusion is 100x out and must never reach the database.
    assert is_plausible_price(2_723_000) is True
    assert is_plausible_price(272_300_000) is False   # 100x too large
    assert is_plausible_price(27_230) is False        # 100x too small
    assert is_plausible_price(0) is False
    assert is_plausible_price(None) is False
    assert PRICE_MIN == 100_000
    assert PRICE_MAX == 100_000_000


def test_listing_requires_identity_fields():
    with pytest.raises(ValueError):
        Listing(store_slug="olcha", source_key="", name_raw="X", price=1_000_000, url="u")
    with pytest.raises(ValueError):
        Listing(store_slug="olcha", source_key="k", name_raw="", price=1_000_000, url="u")
    with pytest.raises(ValueError):
        Listing(store_slug="olcha", source_key="k", name_raw="X", price=1_000_000, url="")


def test_listing_rejects_implausible_price():
    with pytest.raises(ValueError):
        Listing(store_slug="olcha", source_key="k", name_raw="X", price=99, url="u")


def test_listing_is_frozen_and_hashable():
    lst = Listing(store_slug="olcha", source_key="k", name_raw="X", price=1_000_000, url="u")
    assert lst.availability == "UNKNOWN"
    hash(lst)
    with pytest.raises(Exception):
        lst.price = 5
