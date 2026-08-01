"""Offline parse tests for the mediapark client.

Fixture recorded live on 2026-08-01 with:
    GET https://api.v2.mediapark.uz/v1/diginetica/autocomplete?st=Samsung&lang=ru
    Headers: Accept: */*, Content-Type: application/json, Accept-Language: ru,
             Origin: https://mediapark.uz, Referer: https://mediapark.uz/,
             x-device-id: Ywh1FNq17HzyCBJ15BDZl, x-session-id: vzNu2usamNvHs6plQvNO4,
             User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
             (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36

The live call returned 10 products (mediapark's autocomplete has no
pagination and returns only a short ranked list), all of them Samsung
phones, so the fixture keeps the response as recorded, unedited.
"""
import json
import pathlib

import pytest

from narxnoma.matching.features import extract_features
from narxnoma.matching.keys import variant_key
from narxnoma.matching.sim import sim_kind
from narxnoma.sources.mediapark import MediaparkSource, parse
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "mediapark.json"

# FIXTURE: copy these three from one real item in the recorded file.
KNOWN_SOURCE_KEY = "1cc28b2b-d32d-4902-bee9-db3a7318c64a"
KNOWN_PRICE = 2699000            # in SUM, after any unit conversion
KNOWN_URL = "https://mediapark.uz/ru/products/view/smartfon-samsung-sm-a175f-a17-128gb-gray-32921"


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
        assert lst.store_slug == "mediapark"
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


def test_price_is_cast_from_a_string():
    # mediapark's price field is delivered as a string in the raw payload --
    # this pins that the recorded fixture actually exercises that trap
    # (rather than happening to already be numeric) and that parse() casts it.
    raw_by_id = {it["id"]: it for it in payload()["products"]}
    assert isinstance(raw_by_id[KNOWN_SOURCE_KEY]["price"], str)
    by_key = {lst.source_key: lst for lst in parse(payload())}
    assert isinstance(by_key[KNOWN_SOURCE_KEY].price, int)


def test_linkurl_is_used_verbatim_not_reconstructed_from_the_slug():
    # The slug in linkUrl can lie about specs (docs/parsers/mediapark.md
    # section 3) -- it must be prefixed with the host and used exactly as
    # given, never parsed or rebuilt from the item's other fields.
    raw_by_id = {it["id"]: it for it in payload()["products"]}
    by_key = {lst.source_key: lst for lst in parse(payload())}
    for key, lst in by_key.items():
        assert lst.url == "https://mediapark.uz" + raw_by_id[key]["linkUrl"]


def test_malformed_items_are_dropped_not_raised():
    # One bad item must never kill a sweep of several hundred.
    broken = payload()
    broken["products"].append({
        "id": "junk-no-name",
        "name": None,
        "price": "1500000",
        "linkUrl": "/ru/products/view/junk-item-no-name-99999001",
    })
    broken["products"].append({
        "id": "junk-no-price",
        "name": "Junk item with null price",
        "price": None,
        "linkUrl": "/ru/products/view/junk-item-no-price-99999002",
    })
    broken["products"].append({
        # no "id" -- mediapark's own id is what we key on; without it
        # there is nothing to build a source_key from.
        "name": "Junk item with no id",
        "price": "1500000",
        "linkUrl": "/ru/products/view/junk-item-no-id-99999003",
    })
    good_keys = {lst.source_key for lst in parse(payload())}
    result_keys = {lst.source_key for lst in parse(broken)}   # must not raise even with the junk items above
    assert good_keys <= result_keys
    assert "junk-no-name" not in result_keys
    assert "junk-no-price" not in result_keys


def test_parsed_count_is_pinned_to_the_recording():
    """Pin how many of the recorded items survive parsing.

    Retailer responses mix phones with accessories, and the price fence
    silently drops the accessories -- correctly, but silently. Without this
    assertion a change to PRICE_MIN or coerce_price could turn a 4,000 SUM
    screen protector into a catalogue entry and no test would fail.

    Unlike idea's or texnomart's fixtures, this "Samsung" autocomplete
    recording drops nothing: all 10 items have an id, a name, a linkUrl,
    and a positive price string well inside PRICE_MIN/PRICE_MAX (cheapest
    2,699,000 SUM, most expensive 25,555,000 SUM), so all 10 survive
    try_build_listing.
    """
    raw_items = payload()["products"]          # FIXTURE: count the item list in the recorded file
    parsed = parse(payload())
    assert len(raw_items) == 10
    assert len(parsed) == 10                    # nothing in this recording trips the price fence or is malformed


def test_cannot_sweep():
    # mediapark has no full-catalogue browse and no pagination -- can_sweep
    # is the guard callers must honour before ever calling sweep().
    assert MediaparkSource.can_sweep is False


def test_sweep_raises_not_yields_empty():
    # A silent empty iterator here would be indistinguishable from a real,
    # successful, zero-listing harvest run -- exactly the failure mode this
    # project exists to prevent. sweep() must raise loudly instead.
    source = MediaparkSource()
    with pytest.raises(NotImplementedError, match="search-only"):
        source.sweep()


def test_every_listing_yields_a_usable_identity():
    """name_raw is the clustering stage's ONLY handle on what a product is.

    See the uzum module's version of this test for why: a name that yields no
    identity is a product lost from the catalogue, silently and with every
    other test still green. It matters doubly here, because mediapark's slug
    LIES about the specs (docs/parsers/mediapark.md), so `name` is not merely
    the preferred source of identity -- it is the only honest one.

    BRAND is the non-negotiable part and mediapark meets it on all 10
    listings ("Смартфон Samsung Galaxy A17 128GB Gray").

    FULLY KEYABLE: only 4 of 10, the lowest of the seven sources, and the
    reason is a single consistent one: mediapark states STORAGE ALONE for its
    mid-range models -- "Galaxy A17 128GB", "Galaxy A57 256 GB", "Galaxy A36
    128GB", "Galaxy A26 128GB" -- with no RAM figure anywhere in the name.
    Samsung publishes RAM, so `variant_key` requires it and correctly refuses
    rather than guessing. The four that do key are the ones whose names carry
    a memory PAIR (S26 Ultra 12/256, S25 Ultra (12/256), Z Fold 7 12/256,
    S26 Ultra 12/512).

    This is a genuine data limitation, not a parsing defect: the RAM is
    simply absent from the payload's only trustworthy field. It is also the
    smallest source by far (autocomplete returns ~10 ranked items, never
    swept), so the absolute loss is small. If it ever matters, the fix is a
    Samsung model -> RAM table in the matching engine, not a change here.
    """
    features = [(lst, extract_features(lst.name_raw)) for lst in parse(payload())]
    assert len(features) == 10

    brandless = [lst.name_raw for lst, f in features if not f.brand]
    assert not brandless, f"no brand recoverable, so unclusterable: {brandless}"

    keyable = [lst for lst, f in features if variant_key(f, sim_kind(lst.name_raw))]
    # Pinned to the measured value so any regression fails rather than drifts.
    assert len(keyable) == 4, [
        lst.name_raw for lst, f in features if not variant_key(f, sim_kind(lst.name_raw))
    ]

    # The shortfall is entirely "no RAM stated", not a scattering of causes.
    for lst, f in features:
        if not variant_key(f, sim_kind(lst.name_raw)):
            assert f.ram_gb is None, f"unexpected new cause of unkeyability: {lst.name_raw}"
            assert f.storage_gb and f.primary_color, lst.name_raw
