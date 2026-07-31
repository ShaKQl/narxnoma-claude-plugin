import pytest

from narxnoma.sources.base import (
    PRICE_MAX, PRICE_MIN, Listing, coerce_price, is_plausible_price, try_build_listing,
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


def test_try_build_listing_returns_listing_for_valid_input():
    lst = try_build_listing(
        store_slug="olcha", source_key="k", name_raw="X", price=1_000_000, url="u",
    )
    assert isinstance(lst, Listing)
    assert lst.source_key == "k"


def test_try_build_listing_returns_none_for_implausible_price():
    lst = try_build_listing(
        store_slug="olcha", source_key="k", name_raw="X", price=99, url="u",
    )
    assert lst is None


def test_try_build_listing_returns_none_for_missing_url():
    lst = try_build_listing(
        store_slug="olcha", source_key="k", name_raw="X", price=1_000_000, url="",
    )
    assert lst is None


def test_coerce_price_passes_through_int():
    assert coerce_price(3246000) == 3246000


def test_coerce_price_parses_numeric_string():
    assert coerce_price("3246000") == 3246000


def test_coerce_price_rejects_zero_int():
    assert coerce_price(0) is None


def test_coerce_price_rejects_zero_string():
    assert coerce_price("0") is None


def test_coerce_price_rejects_empty_string():
    assert coerce_price("") is None


def test_coerce_price_rejects_none():
    assert coerce_price(None) is None


def test_coerce_price_rejects_non_numeric_string():
    assert coerce_price("not-a-price") is None


def test_coerce_price_parses_float_ish_string():
    # olcha's total_price arrives as a string like "3246000.0" in practice.
    assert coerce_price("3246000.0") == 3246000


def test_coerce_price_rejects_negative_value():
    # A negative price is meaningless, and the plausibility fences would
    # reject it anyway -- coerce it away at the source instead.
    assert coerce_price(-5000) is None


def test_try_build_listing_returns_none_for_unexpected_keyword_argument():
    # Fix: a caller passing wrong/missing kwargs raises TypeError, not
    # ValueError -- that is a bug in the client, but it must still be
    # logged and dropped rather than killing the sweep mid-run.
    lst = try_build_listing(
        store_slug="olcha", source_key="k", name_raw="X", price=1_000_000, url="u",
        unexpected_kwarg="surprise",
    )
    assert lst is None
