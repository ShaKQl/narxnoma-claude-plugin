"""Offline parse tests for the idea client.

Fixture recorded live on 2026-07-31 with:
    GET https://api.idea.uz/api/v2/search?search=Samsung&quantity=100&type[]=shops&type[]=products
    Headers: Accept: application/json, Accept-Language: uz,
             Origin: https://idea.uz, Referer: https://idea.uz/,
             User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
             (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36

The live call returned 74 products; the fixture keeps the first 20 (recorded
order, fields untouched) so it stays readable.
"""
import json
import pathlib

from narxnoma.sources.idea import parse
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "idea.json"

# FIXTURE: copy these three from one real item in the recorded file.
KNOWN_SOURCE_KEY = "10506"
KNOWN_PRICE = 16199000            # in SUM, after any unit conversion
KNOWN_URL = "https://idea.uz/product/10506-smartfon-samsung-galaxy-s25-ultra-12-256-titanium-blue"


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
        assert lst.store_slug == "idea"
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


def test_malformed_items_are_dropped_not_raised():
    # One bad item must never kill a sweep of several hundred.
    broken = payload()
    broken["products"].append({
        "id": 999999001,
        "name": None,
        "current_price": 1500000,
        "url": "https://idea.uz/product/999999001-junk-item-no-name",
    })
    broken["products"].append({
        "name": "Junk item with null price",
        "current_price": None,
        "url": "https://idea.uz/product/999999002-junk-item-no-price",
        # no "id" -- idea's own id is what we key on; without it there is
        # nothing to build a source_key from.
    })
    good_keys = {lst.source_key for lst in parse(payload())}
    result_keys = {lst.source_key for lst in parse(broken)}   # must not raise even with the junk items above
    assert good_keys <= result_keys
    assert "999999001" not in result_keys
    assert "999999002" not in result_keys


def test_parsed_count_is_pinned_to_the_recording():
    """Pin how many of the recorded items survive parsing.

    Retailer responses mix phones with accessories, and the price fence
    silently drops the accessories -- correctly, but silently. Without this
    assertion a change to PRICE_MIN or coerce_price could turn a 4,000 SUM
    screen protector into a catalogue entry and no test would fail.

    Unlike texnomart's fixture, nothing here falls outside the price fence:
    a "Samsung" search returns Samsung-branded appliances (vacuum cleaners,
    fridges, TVs) alongside phones, and the cheapest item in this recording
    -- id 1042, "VCC 5252 Black" (a vacuum cleaner), 999,000 SUM -- is still
    well above PRICE_MIN (100,000 SUM). All 20 recorded items have an id,
    a name, a url, and a positive current_price, so all 20 survive
    try_build_listing and none are dropped.
    """
    raw_items = payload()["products"]          # FIXTURE: count the item list in the recorded file
    parsed = parse(payload())
    assert len(raw_items) == 20
    assert len(parsed) == 20                    # nothing in this recording trips the price fence
