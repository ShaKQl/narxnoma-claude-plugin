"""Offline parse tests for the alifshop client.

Fixture recorded live on 2026-07-31 with:
    POST https://gw.alifshop.uz/web/client/search/full-text
    Body: {"query": "Samsung", "page": 0, "size": 20}
    Headers: Accept: application/json, Accept-Language: ru,
             Content-Type: application/json,
             service-token: service-token-alifshop,
             Origin: https://alifshop.uz, Referer: https://alifshop.uz/,
             User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
             (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36

The live call returned n_pages=52, n_items=1034 total for "Samsung" across
alifshop's whole catalogue (phones and Samsung-branded appliances mixed
together); this fixture is just page 0 (20 items, the server-side max
`size`), saved verbatim.
"""
import json
import pathlib

from narxnoma.sources.alifshop import parse
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "alifshop.json"

# FIXTURE: copy these three from one real item in the recorded file.
KNOWN_SOURCE_KEY = "4ab27e23-1f44-4c49-8a0d-213b82ab40a1"
KNOWN_PRICE = 1730000            # in SUM, after any unit conversion (173000000 tiyin // 100)
KNOWN_URL = "https://alifshop.uz/moderated-offer/smartfon-samsung-galaxy-a07-4-128-gb-cherniy-1762320736"


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
        assert lst.store_slug == "alifshop"
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


def test_tiyin_is_divided_by_100_not_partially():
    """The headline trap: alifshop reports price in tiyin (1/100 SUM). A
    completely forgotten divisor lands above PRICE_MAX and fails loudly, but
    a partial or conditional divisor bug produces plausible-looking prices
    that are 100x wrong and would pass every fence silently. Read the raw
    integer straight out of the fixture -- not a synthetic number -- and
    assert the parsed price is exactly that value floor-divided by 100.
    """
    raw_item = next(it for it in payload()["items"] if it["id"] == KNOWN_SOURCE_KEY)
    raw_price = raw_item["price"]
    assert raw_price == 173000000
    by_key = {lst.source_key: lst for lst in parse(payload())}
    assert by_key[KNOWN_SOURCE_KEY].price == raw_price // 100


def test_malformed_items_are_dropped_not_raised():
    # One bad item must never kill a sweep of several hundred.
    broken = payload()
    broken["items"].append({
        "id": "99999999-0000-0000-0000-000000000001",
        "slug": "junk-item-null-price",
        "price": None,
        "product": {"name": "Junk item with null price"},
        "partner": {"slug": "junk-partner"},
    })
    broken["items"].append({
        "id": "99999999-0000-0000-0000-000000000002",
        "slug": "junk-item-no-name",
        "price": 500000000,
        "product": {},          # no "name" -- nothing to carry as name_raw
        "partner": {"slug": "junk-partner"},
    })
    good_keys = {lst.source_key for lst in parse(payload())}
    result_keys = {lst.source_key for lst in parse(broken)}   # must not raise even with the junk items above
    assert good_keys <= result_keys
    assert "99999999-0000-0000-0000-000000000001" not in result_keys
    assert "99999999-0000-0000-0000-000000000002" not in result_keys


def test_parsed_count_is_pinned_to_the_recording():
    """Pin how many of the recorded items survive parsing.

    Retailer responses mix phones with accessories, and the price fence
    silently drops the accessories -- correctly, but silently. Without this
    assertion a change to PRICE_MIN or coerce_price could turn a 4,000 SUM
    screen protector into a catalogue entry and no test would fail.

    Unlike idea/texnomart, nothing is dropped in this recording: this page
    of the "Samsung" search happens to be sorted cheapest-first, and all 20
    items are genuine Galaxy A07/A16/A17 phone listings (see the module
    docstring) with a valid id, slug, product.name, and a positive price
    that survives the tiyin conversion well inside [PRICE_MIN, PRICE_MAX].
    All 20 recorded items therefore survive try_build_listing.
    """
    raw_items = payload()["items"]          # FIXTURE: count the item list in the recorded file
    parsed = parse(payload())
    assert len(raw_items) == 20
    assert len(parsed) == 20                 # nothing in this recording trips the price fence
