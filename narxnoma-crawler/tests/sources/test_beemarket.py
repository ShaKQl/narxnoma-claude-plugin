"""Offline parse tests for the beemarket client.

Fixture recorded live on 2026-07-31 with:
    GET https://market.beeline.uz/api/web/categories/smartfony/products?page=1&is_bshop=1
    Headers: Accept: */*, Accept-Language: ru,
             Referer: https://market.beeline.uz/,
             User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
             (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36

This is NOT the endpoint named in the task brief (the generic
`/api/web/search?q=&is_bshop=1` sweep across all ~270 pages of BeeMarket's
entire electronics catalogue). A live probe found that
`/api/web/categories/smartfony/products` -- the same request BeeMarket's own
category page issues -- returns only the `smartfony` category server-side:
436 items across 28 pages instead of 4,306 items across 270 pages for the
same "is_bshop=1" scope. The response envelope (`data.data` list,
`data.last_page`) and item shape are identical between the two endpoints, so
`parse()` works unchanged against either; `sweep()` uses the narrower
endpoint, `search(query)` uses the documented generic one (see beemarket.py
docstring for the probe results in full).
"""
import json
import pathlib

from narxnoma.sources.beemarket import PHONE_CATEGORY_SLUGS, _filter_phone_listings, parse
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "beemarket.json"

# FIXTURE: copy these three from one real item in the recorded file.
KNOWN_SOURCE_KEY = "187577"
KNOWN_PRICE = 1499000            # in SUM, after any unit conversion
KNOWN_URL = "https://market.beeline.uz/smartfony/smartfon-huawei-nova-y63-4128-black"


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_exists_and_is_not_empty():
    """Guards against the parse tests passing vacuously over an empty file."""
    assert FIXTURE.exists(), f"record the fixture first: {FIXTURE}"
    assert payload()


def test_parse_returns_listings():
    listings = parse(payload())
    assert listings, "parse() found nothing in a real recorded response"


def test_every_listing_has_provenance():
    # A price we cannot attribute to a specific retailer listing is worthless.
    for lst in parse(payload()):
        assert lst.store_slug == "beemarket"
        assert lst.source_key
        assert lst.name_raw
        assert lst.url.startswith("http")


def test_every_price_is_an_integer_inside_the_fences():
    for lst in parse(payload()):
        assert isinstance(lst.price, int)
        assert PRICE_MIN <= lst.price <= PRICE_MAX


def test_source_keys_are_unique_within_one_response():
    # source_key is the upsert key; duplicates would silently collapse offers.
    keys = [lst.source_key for lst in parse(payload())]
    assert len(keys) == len(set(keys))


def test_known_product_parses_exactly():
    by_key = {lst.source_key: lst for lst in parse(payload())}
    assert KNOWN_SOURCE_KEY in by_key
    assert by_key[KNOWN_SOURCE_KEY].price == KNOWN_PRICE
    assert by_key[KNOWN_SOURCE_KEY].url == KNOWN_URL


def test_uses_actual_price_not_the_struck_through_price():
    # `price` is the pre-discount list price and must never be used --
    # every recorded item's actual_price is lower than its price, so this
    # would fail loudly if the fallback chain regressed to reading `price`
    # first.
    raw_by_id = {str(it["id"]): it for it in payload()["data"]["data"]}
    for lst in parse(payload()):
        raw = raw_by_id[lst.source_key]
        assert raw["actual_price"] != raw["price"]
        assert lst.price == raw["actual_price"]


def test_falls_back_to_discount_price_then_price_when_actual_price_is_absent():
    # Every item in the recorded fixture has a non-null actual_price, so the
    # discount_price/price fallback branches never run in the other tests
    # above. Force each fallback in turn on real items so a broken chain
    # doesn't pass the suite silently.
    data = payload()
    products = data["data"]["data"]

    only_discount = products[0]
    only_discount["actual_price"] = None
    expected_discount_price = only_discount["discount_price"]

    only_price = products[1]
    only_price["actual_price"] = None
    only_price["discount_price"] = None
    expected_price = only_price["price"]

    by_key = {lst.source_key: lst for lst in parse(data)}
    assert by_key[str(only_discount["id"])].price == expected_discount_price
    assert by_key[str(only_price["id"])].price == expected_price


def test_malformed_items_are_dropped_not_raised():
    # One bad item must never kill a sweep of several hundred.
    broken = payload()
    broken["data"]["data"].append({
        "name": "Junk item with no id",
        "slug": "junk-item-no-id",
        "category": {"slug": "smartfony"},
        "actual_price": 1500000,
        "price": 1800000,
        # no "id" -- beemarket's own numeric id is what we key on; without
        # it there is nothing to build a source_key from.
    })
    broken["data"]["data"].append({
        "id": 999999002,
        "name": "Junk item with no price",
        "slug": "junk-item-no-price",
        "category": {"slug": "smartfony"},
        "actual_price": None,
        "discount_price": None,
        "price": None,
    })
    good_keys = {lst.source_key for lst in parse(payload())}
    result_keys = {lst.source_key for lst in parse(broken)}   # must not raise even with the junk items above
    assert good_keys <= result_keys
    assert "999999002" not in result_keys


def test_parsed_count_is_pinned_to_the_recording():
    """Pin how many of the recorded items survive parsing.

    Retailer responses mix phones with accessories, and the price fence
    silently drops the accessories -- correctly, but silently. Without this
    assertion a change to PRICE_MIN or coerce_price could turn a 4,000 SUM
    screen protector into a catalogue entry and no test would fail.

    Unlike a recording of the generic search endpoint, this fixture was
    recorded from the category-scoped endpoint sweep() actually calls (see
    module docstring), so every one of its 16 items is already a phone with
    a numeric id, a slug, and a positive actual_price -- all 16 survive
    try_build_listing and none are dropped.
    """
    raw_items = payload()["data"]["data"]      # FIXTURE: count the item list in the recorded file
    parsed = parse(payload())
    assert len(raw_items) == 16
    assert len(parsed) == 16                    # nothing in this recording trips the price fence


def test_filter_phone_listings_keeps_only_smartfony():
    """sweep()'s category filter, exercised directly against the recorded
    fixture rather than over the network.

    The recorded fixture already comes from the category-scoped endpoint,
    so every one of its 16 items is already `smartfony` -- this test proves
    the filter is not a no-op by injecting one item from a category
    BeeMarket's generic (unscoped) search is known to mix in
    ("headphones", observed live in `/api/web/search?q=&is_bshop=1`) and
    asserting it gets dropped while the 16 real phones survive.
    """
    assert PHONE_CATEGORY_SLUGS == frozenset({"smartfony"})
    data = payload()
    data["data"]["data"].append({
        "id": 999999003,
        "name": "Honor FreeArc Wired Charging Cable",
        "slug": "honor-freearc-wired-charging-cable",
        "category": {"slug": "headphones"},
        "actual_price": 150000,
        "price": 180000,
    })
    listings = parse(data)
    filtered = _filter_phone_listings(listings)
    assert len(filtered) == 16
    assert all(lst.raw.get("category", {}).get("slug") == "smartfony" for lst in filtered)
    assert "999999003" not in {lst.source_key for lst in filtered}
