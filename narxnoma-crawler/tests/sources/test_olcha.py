"""Offline parse tests for the olcha client.

Fixture recorded live on 2026-07-31 with:
    GET https://mobile.olcha.uz/api/v2/products?page=1&per_page=20&category=telefony
    Headers: Accept: */*, Accept-Language: ru, clientmodel: web,
             Origin: https://olcha.uz, Referer: https://olcha.uz/,
             User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
             (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36
"""
import json
import pathlib

from narxnoma.matching.features import extract_features
from narxnoma.matching.keys import variant_key
from narxnoma.matching.sim import sim_kind
from narxnoma.sources.olcha import parse
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "olcha.json"

# FIXTURE: copy these three from one real item in the recorded file.
KNOWN_SOURCE_KEY = "smartfon-xiaomi-redmi-note-17-6256gb-celestial-purple"
KNOWN_PRICE = 3246000            # in SUM, after any unit conversion
KNOWN_URL = "https://olcha.uz/ru/product/view/smartfon-xiaomi-redmi-note-17-6256gb-celestial-purple"


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
        assert lst.store_slug == "olcha"
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


def test_falls_back_to_total_price_when_discount_price_is_absent():
    # Every item in the recorded fixture has a non-null discount_price, so
    # the total_price-as-string fallback branch never runs in the other
    # tests above. The live API types these two fields differently
    # (discount_price: int, total_price: string) and only discount_price is
    # exercised by the recording -- a broken string coercion here would
    # pass the whole suite silently. Force the fallback by nulling out
    # discount_price on one real item and keep its (string) total_price.
    data = payload()
    products = data["data"]["products"]
    target = products[0]
    target["discount_price"] = None
    expected_price = int(float(target["total_price"]))

    by_key = {lst.source_key: lst for lst in parse(data)}
    assert target["alias"] in by_key
    result = by_key[target["alias"]]
    assert isinstance(result.price, int)
    assert result.price == expected_price


def test_malformed_items_are_dropped_not_raised():
    # One bad item must never kill a sweep of several hundred.
    broken = payload()
    broken["data"]["products"].append({
        "name_ru": None,
        "discount_price": None,
        "total_price": None,
        "alias": "junk-item-no-name",
        "quantity": 0,
    })
    broken["data"]["products"].append({
        "discount_price": 1_500_000,
        "total_price": 1_500_000,
        "alias": "junk-item-no-name-field",
        "quantity": 3,
    })
    good_keys = {lst.source_key for lst in parse(payload())}
    result_keys = {lst.source_key for lst in parse(broken)}   # must not raise even with the junk items above
    assert good_keys <= result_keys
    assert "junk-item-no-name" not in result_keys
    assert "junk-item-no-name-field" not in result_keys


def test_every_listing_yields_a_usable_identity():
    """name_raw is the clustering stage's ONLY handle on what a product is.

    Nothing downstream re-reads the retailer's response: clustering is handed
    `name_raw` and has to recover an identity from it. A name that cannot
    yield one is not a slightly worse name -- it is a product that silently
    drops out of the catalogue, with no key to file it under and no error to
    notice. The uzum version of this test is what caught a whole source
    parsing to brandless names while every other test stayed green.

    BRAND is the non-negotiable part and olcha meets it on every listing: its
    names are fully composed ("Смартфон Xiaomi Redmi Note 17 6/256GB
    Celestial Purple").

    FULLY KEYABLE: 17 of 20. The three that fall short are the `is_parent: 1`
    grouping cards -- "Смартфон Xiaomi Redmi Note 17", "Смартфон Honor X5d
    Plus", "Смартфон Honor X7e" -- which olcha returns alongside their own
    children (ids 594227, 594122, 594118 are the parents of the other 17
    rows). A parent card names no memory tier and no colour because it stands
    for all of them, so `variant_key` correctly refuses it. This is a genuine
    property of olcha's catalogue, not a parsing defect: the priced variants
    are all present as separate listings.
    """
    features = [(lst, extract_features(lst.name_raw)) for lst in parse(payload())]

    brandless = [lst.name_raw for lst, f in features if not f.brand]
    assert not brandless, f"no brand recoverable, so unclusterable: {brandless}"

    keyable = [lst for lst, f in features if variant_key(f, sim_kind(lst.name_raw))]
    # Pinned to the measured value so any regression fails rather than drifts.
    assert len(keyable) == 17, [
        lst.name_raw for lst, f in features if not variant_key(f, sim_kind(lst.name_raw))
    ]
