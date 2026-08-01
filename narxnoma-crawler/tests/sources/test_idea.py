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

from narxnoma.matching.brands import BRAND_ALIASES, BRANDS
from narxnoma.matching.features import extract_features
from narxnoma.matching.keys import variant_key
from narxnoma.matching.sim import sim_kind
from narxnoma.sources.idea import BRAND_QUERIES, PHONE_CATEGORY_IDS, _filter_phone_listings, parse
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


def test_brand_queries_cover_the_major_brands_the_list_used_to_omit():
    """BRAND_QUERIES is idea's entire reach: a brand missing from it is
    permanently invisible to the catalogue since idea has no pagination and
    no browsable catalogue. This pins that OPPO, Huawei and vivo -- three
    major sellers in this market -- and Xiaomi's "redmi" alias are present,
    so a future refactor of BRAND_QUERIES can't silently narrow the sweep.
    """
    lowered = {q.lower() for q in BRAND_QUERIES}
    for brand in ("oppo", "huawei", "vivo"):
        assert brand in lowered
    assert "redmi" in lowered, "alias keys must be queried, not just canonical brands"


def test_brand_queries_is_derived_from_the_canonical_vocabulary_not_hardcoded():
    # Every canonical brand and every alias key must be queried, and nothing
    # else -- BRAND_QUERIES must track narxnoma.matching.brands exactly.
    # BRAND_QUERIES is a tuple (shared with alifshop.py via
    # narxnoma.sources.brand_queries), so sort as a list for comparison.
    assert set(BRAND_QUERIES) == set(BRANDS) | set(BRAND_ALIASES)
    assert list(BRAND_QUERIES) == sorted(BRAND_QUERIES)


def test_filter_phone_listings_keeps_only_category_55():
    """sweep()'s category filter, exercised directly against the recorded
    fixture rather than over the network. Of the fixture's 20 items, only
    the 9 category-55 smartphones should survive; the vacuum cleaners (26),
    fridges (24) and TV (9) must all be dropped.
    """
    assert PHONE_CATEGORY_IDS == frozenset({55})
    listings = parse(payload())
    filtered = _filter_phone_listings(listings)
    assert len(filtered) == 9
    assert all(lst.raw.get("category_id") == 55 for lst in filtered)
    dropped_ids = {lst.raw.get("category_id") for lst in listings} - {55}
    assert dropped_ids == {26, 24, 9}


def test_name_raw_is_taken_from_title_name_not_name():
    """idea's `name` field is BRANDLESS and `title_name` is not.

    idea stores the model half in `name` ("VCC 5252 Black", "Galaxy S25 Ultra
    12/256 Titanium Blue") and the full title in `title_name` ("Samsung VCC
    5252 Black changyutgichi"). The client read `name`, so every idea listing
    reached the clustering stage with no brand -- and brand is a hard
    identity field, so all 20 of them keyed to None and would have dropped
    out of the catalogue in silence. This pins which field is used.
    """
    by_key = {lst.source_key: lst for lst in parse(payload())}
    items = {str(it["id"]): it for it in payload()["products"]}

    with_title = [k for k, it in items.items() if (it.get("title_name") or "").strip()]
    assert with_title, "fixture must exercise the title_name path"
    for key in with_title:
        assert by_key[key].name_raw == items[key]["title_name"].strip()

    # The raw payload is kept untouched, so `name` is still available to
    # anything downstream that wants the model half on its own.
    for key, lst in by_key.items():
        assert lst.raw["name"] == items[key]["name"]


def test_every_listing_yields_a_usable_identity():
    """name_raw is the clustering stage's ONLY handle on what a product is.

    See the uzum module's version of this test for why: a name that yields no
    identity is a product lost from the catalogue, silently and with every
    other test still green. idea is the source that proved the point twice
    over -- before the title_name fix, 0 of these 20 listings recovered a
    brand and 0 were keyable, with the whole suite passing.

    Measured over the PHONE listings (the 9 category-55 items -- this is what
    sweep() actually yields; parse() stays unfiltered on purpose and its
    other 11 items are Samsung vacuum cleaners, fridges and a TV whose names
    can never carry phone specs):

      BRAND recoverable: 7 of 9. idea is the ONE source that cannot reach
        9 of 9, and the reason is in its own data, not in the parsing: for
        two records -- ids 10516 "Galaxy S25 12/128 Silver Shadow" and 10517
        "Galaxy S25 Ultra 12/256 Titanium Gray" -- idea's `title_name` is
        byte-identical to the brandless `name`, so there is no brand anywhere
        in either text field. (Their `slug` does contain "samsung"; reading
        identity out of a slug is a change to the client's contract and is
        reported rather than made here.)

      FULLY KEYABLE: 6 of 9. The 7th is "Galaxy A56 8/128gb Olive" --
        brand, RAM and storage all extract, but "olive" is not in COLOR_MAP,
        and colour is a hard identity field. A vocabulary gap.

    Both floors are pinned to today's measurement so a regression fails here.
    """
    phones = _filter_phone_listings(parse(payload()))
    assert len(phones) == 9

    features = [(lst, extract_features(lst.name_raw)) for lst in phones]
    with_brand = [lst for lst, f in features if f.brand]
    assert len(with_brand) == 7, [lst.name_raw for lst, f in features if not f.brand]

    keyable = [lst for lst, f in features if variant_key(f, sim_kind(lst.name_raw))]
    assert len(keyable) == 6, [
        lst.name_raw for lst, f in features if not variant_key(f, sim_kind(lst.name_raw))
    ]
