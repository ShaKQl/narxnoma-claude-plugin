"""Offline parse tests for the uzum client.

Fixture recorded live on 2026-08-01 with:
    Step 1a - mint an anonymous token:
        POST https://id.uzum.uz/api/auth/token
        Headers: Accept: */*, Accept-Language: ru-RU (required),
                 Content-Type: application/json,
                 Referer: https://uzum.uz/ (required),
                 User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
                 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36,
                 x-iid: <uuid4>
        Body: {}
        Response: 204 No Content; token read from the Set-Cookie: access_token=<JWT> header.

    Step 1b - the makeSearch query itself:
        POST https://graphql.uzum.uz/
        Headers: Authorization: Bearer <token>, Content-Type: application/json,
                 apollographql-client-name: web-customers,
                 apollographql-client-version: 1.63.2, x-iid: <same uuid4>,
                 city-id: 1, Origin: https://uzum.uz, Referer: https://uzum.uz/,
                 User-Agent: <as above>
        Body: {"query": "<getMakeSearch, see docs/parsers/uzum.md section 3>",
               "variables": {"q": {"text": "Samsung", "showAdultContent": "TRUE",
                                    "filters": [], "sort": "BY_RELEVANCE_DESC",
                                    "pagination": {"offset": 0, "limit": 72}}}}

The live call reported total=565 for "Samsung" and returned 72 items on this
page; saved verbatim except trimmed to the first 20 items (26 SKUs across
them) so the fixture stays readable. No Accept-Language was sent on the
graphql call itself (not in the required-header set -- see
docs/parsers/uzum.md section 2), so the recorded card titles and
characteristic keys came back in Uzbek ("Smartfonlar Android", "Xotira",
"Rang") rather than the Russian shown in the doc's examples -- category
FILTERING still works because it keys on category.id (15271), not the
locale-dependent title text.
"""
import json
import pathlib

from narxnoma.sources.base import PRICE_MAX, PRICE_MIN
from narxnoma.sources.uzum import parse

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "uzum.json"

# FIXTURE: copy these three from one real item in the recorded file.
# productId 1978967, skuId 6998861 -- the SKU whose characteristicValues state
# its own memory ("Xotira": "8/256GB") while the card TITLE also lists both
# "6/128" and "8/256" for the sibling SKU -- i.e. the live instance of the
# exact card-range-vs-SKU trap docs/parsers/uzum.md section 5b warns about.
KNOWN_SOURCE_KEY = "6998861"
KNOWN_PRICE = 3068010            # sellPrice, in SUM -- NOT fullPrice (10000000)
KNOWN_URL = "https://uzum.uz/ru/product/1978967?skuId=6998861"
KNOWN_NAME_RAW = "Smartfon Samsung Galaxy A17 4G 8/256GB Qora"


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
        assert lst.store_slug == "uzum"
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


def test_known_product_uses_sellprice_not_fullprice():
    """The headline trap: fullPrice (10,000,000 for this SKU) is a
    struck-through fantasy figure -- sellPrice (3,068,010) is the real one.
    Read the raw integer straight out of the fixture, not a synthetic number.
    """
    raw_item = next(
        it for it in payload()["data"]["makeSearch"]["items"]
        if it["catalogCard"]["productId"] == 1978967
    )
    raw_sku = next(
        s for s in raw_item["catalogCard"]["skuList"] if s["id"] == 6998861
    )
    assert raw_sku["sellPrice"] == 3068010
    assert raw_sku["fullPrice"] == 10000000
    by_key = {lst.source_key: lst for lst in parse(payload())}
    assert by_key[KNOWN_SOURCE_KEY].price == raw_sku["sellPrice"]


def test_known_product_name_raw_strips_the_cards_other_memory_tiers():
    """docs/parsers/uzum.md section 5b: the card title for productId 1978967
    lists BOTH "6/128" and "8/256" ("...Galaxy A17 4G, 6/128, 8/256,..."),
    but this SKU (skuId 6998861) states its own memory ("8/256GB" via the
    "Xotira" characteristic). name_raw must reflect the SKU's own spec, not
    let the card's overall range leak in -- this is the exact bug that once
    reported 2,672,010 for a phone whose true price was 3,068,010.
    """
    by_key = {lst.source_key: lst for lst in parse(payload())}
    name = by_key[KNOWN_SOURCE_KEY].name_raw
    assert name == KNOWN_NAME_RAW
    assert "6/128" not in name
    assert "8/256GB" in name


def test_raw_carries_untouched_card_title_and_characteristic_values():
    """The clustering stage must be able to redo name-building without
    re-crawling -- so the untouched card title and the SKU's full
    characteristicValues list must survive into Listing.raw verbatim.
    """
    by_key = {lst.source_key: lst for lst in parse(payload())}
    lst = by_key[KNOWN_SOURCE_KEY]
    assert lst.raw["card_title"] == (
        "Smartfon Samsung Galaxy A17 4G, 6/128, 8/256, sAMOLED 90 Hz, 50 Mp, 5000 mA/h, 25 Вт"
    )
    assert lst.raw["characteristic_values"] == [
        {"title": "8/256GB", "characteristic": {"title": "Xotira"}},
        {"title": "Qora", "characteristic": {"title": "Rang"}},
    ]


def test_malformed_items_are_dropped_not_raised():
    # One bad item must never kill a sweep of several hundred.
    broken = payload()
    items = broken["data"]["makeSearch"]["items"]
    items.append({
        "catalogCard": {
            "__typename": "SkuGroupCard",
            "productId": 9999901,
            "title": "Junk item with null price",
            "category": {"id": 15271, "title": "Smartfonlar Android"},
            "skuList": [
                {"id": 99999011, "sellPrice": None, "fullPrice": None,
                 "availableAmount": 5, "characteristicValues": []},
            ],
        }
    })
    items.append({
        "catalogCard": {
            "__typename": "SkuGroupCard",
            "productId": 9999902,
            "title": "",  # no title, no Модель -- nothing to build a name from
            "category": {"id": 15272, "title": "iOS"},
            "skuList": [
                {"id": 99999021, "sellPrice": 5000000, "fullPrice": 5000000,
                 "availableAmount": 5, "characteristicValues": []},
            ],
        }
    })
    good_keys = {lst.source_key for lst in parse(payload())}
    result_keys = {lst.source_key for lst in parse(broken)}   # must not raise
    assert good_keys <= result_keys
    assert "99999011" not in result_keys
    assert "99999021" not in result_keys


def test_errors_key_returns_empty_list_not_raise():
    """GraphQL signals failure as HTTP 200 with an `errors` key, not an HTTP
    error status (docs/parsers/uzum.md section 2). parse() must recognise
    that shape and return [] rather than raising or returning garbage --
    the live client (UzumSource._fetch) is what raises on this, so a broken
    sweep call is loud instead of silently looking like an empty brand.
    """
    broken_response = {
        "data": None,
        "errors": [{"message": "HTTP fetch failed from 'search-gateway': 4.."}],
    }
    assert parse(broken_response) == []


def test_off_category_items_are_dropped():
    """Relevance search mixes in cases, chargers and vacuum cleaners --
    category.id must be 15271 (Android) or 15272 (iPhone). None of this
    recording's 20 items happen to be off-category (all are 15271), so this
    is covered with a synthetic item rather than the fixture.
    """
    broken = payload()
    items = broken["data"]["makeSearch"]["items"]
    items.append({
        "catalogCard": {
            "__typename": "SkuGroupCard",
            "productId": 8888801,
            "title": "Chexol dlya telefona",
            "category": {"id": 20001, "title": "Aksessuary"},
            "skuList": [
                {"id": 88888011, "sellPrice": 50000, "fullPrice": 50000,
                 "availableAmount": 10, "characteristicValues": []},
            ],
        }
    })
    result_keys = {lst.source_key for lst in parse(broken)}
    assert "88888011" not in result_keys


def test_zero_stock_sku_is_kept_as_out_of_stock():
    """Deliberate inversion of docs/parsers/uzum.md section 4 ("filter to
    availableAmount > 0; zero-stock SKUs are phantom listings"): that
    instruction was written for a target-driven matcher hunting one phone.
    This is an aggregator cataloguing everything -- a zero-stock SKU is a
    real observation (this seller is out of this variant right now), so it
    is kept with availability="OUT_OF_STOCK" rather than dropped. None of
    this recording's real SKUs happen to be zero-stock, so covered
    synthetically.
    """
    broken = payload()
    items = broken["data"]["makeSearch"]["items"]
    items.append({
        "catalogCard": {
            "__typename": "SkuGroupCard",
            "productId": 7777701,
            "title": "Smartfon Samsung Galaxy Zero Stock Test",
            "category": {"id": 15271, "title": "Smartfonlar Android"},
            "skuList": [
                {"id": 77777011, "sellPrice": 2500000, "fullPrice": 2500000,
                 "availableAmount": 0, "characteristicValues": []},
            ],
        }
    })
    by_key = {lst.source_key: lst for lst in parse(broken)}
    assert "77777011" in by_key
    assert by_key["77777011"].availability == "OUT_OF_STOCK"


def test_esim_only_variant_is_kept():
    """Deliberate inversion of docs/parsers/uzum.md section 6: that section
    screens eSIM-only variants OUT because they were the wrong answer to a
    specific target query. Here an eSIM-only iPhone is a legitimate, separate
    offer at a genuinely different price, so it must be recorded, not
    dropped -- with whatever SIM information exists surviving into raw for
    the clustering stage to use later. None of this recording's real items
    are iPhones with SIM characteristics, so covered synthetically.
    """
    broken = payload()
    items = broken["data"]["makeSearch"]["items"]
    items.append({
        "catalogCard": {
            "__typename": "SkuGroupCard",
            "productId": 6666601,
            "title": "Apple smartfon iPhone 17 Air 256GB, 512GB, 1TB, eSIM",
            "category": {"id": 15272, "title": "iOS"},
            "skuList": [
                {"id": 66666011, "sellPrice": 18099000, "fullPrice": 18099000,
                 "availableAmount": 4,
                 "characteristicValues": [
                     {"title": "17 Air 256GB (eSIM)", "characteristic": {"title": "Модель"}},
                     {"title": "e-SIM", "characteristic": {"title": "Сим-карта"}},
                 ]},
            ],
        }
    })
    by_key = {lst.source_key: lst for lst in parse(broken)}
    assert "66666011" in by_key
    lst = by_key["66666011"]
    sim_values = [
        cv["title"] for cv in lst.raw["characteristic_values"]
        if "sim" in cv["characteristic"]["title"].lower() or "сим" in cv["characteristic"]["title"].lower()
    ]
    assert sim_values == ["e-SIM"]


def test_parsed_count_is_pinned_to_the_recording():
    """Pin how many of the recorded items survive parsing.

    Retailer responses mix phones with accessories, and the price fence
    silently drops the accessories -- correctly, but silently. Without this
    assertion a change to PRICE_MIN or coerce_price could turn a 4,000 SUM
    screen protector into a catalogue entry and no test would fail.

    This recording is 20 catalogCards / 26 SKUs total (some cards carry more
    than one SKU -- see docs/parsers/uzum.md section 5). All 20 cards are
    category 15271 (Android); every SKU has a positive sellPrice well inside
    [PRICE_MIN, PRICE_MAX] (1,490,000-13,000,000 SUM), a non-empty
    characteristicValues-or-title-derived name, and a valid id. Nothing in
    this recording trips a fence or a required-field check, so all 26 SKUs
    survive try_build_listing -- 0 dropped.
    """
    raw_items = payload()["data"]["makeSearch"]["items"]
    raw_sku_count = sum(len(it["catalogCard"].get("skuList") or []) for it in raw_items)
    parsed = parse(payload())
    assert len(raw_items) == 20
    assert raw_sku_count == 26
    assert len(parsed) == 26   # nothing dropped in this recording
