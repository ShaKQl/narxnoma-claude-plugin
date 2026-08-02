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

import pytest
import requests

from narxnoma.matching import extract_features
from narxnoma.sources import uzum
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN
from narxnoma.sources.uzum import _build_name_raw, _char_kind, parse

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
    the live client (UzumSource._fetch_payload) is what raises on this, so a broken
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


def test_every_listing_yields_a_usable_identity():
    """name_raw is the clustering stage's ONLY handle on what a product is.

    Nothing downstream re-reads the retailer's response: clustering is
    handed `name_raw` and must recover, at minimum, the brand and the
    storage tier from it. A name that cannot yield both is not a slightly
    worse name -- it is a product that silently drops out of the catalogue,
    because there is no key to file it under and no error to notice.

    The whole test suite passed while two of these 26 listings parsed to
    "Smartfon Samsung Galaxy A16 <colour>" -- brand-only, no memory at all
    -- because every other test asserted that name_raw was *non-empty*, not
    that it was *usable*. This asserts usable.

    RAM is deliberately not asserted: `scan_memory` suppresses RAM for Apple
    on purpose (Apple publishes none, so any figure came from a reseller's
    wording), so a correct iPhone name legitimately yields ram_gb=None.
    Brand and storage have no such exemption.
    """
    unkeyable = []
    for lst in parse(payload()):
        features = extract_features(lst.name_raw)
        if not (features.brand and features.storage_gb):
            unkeyable.append((lst.source_key, lst.name_raw, lst.raw["card_title"]))
    assert not unkeyable, (
        "these listings cannot be keyed by the clustering stage and would be "
        f"lost from the catalogue: {unkeyable}"
    )


def test_char_kind_classifies_every_observed_key():
    """docs/parsers/uzum.md section 7's observed-key list, exercised.

    `RAM/ROM` was named in that list from the start and still classified as
    "other" -- `normalize` folds it to "ram rom", which no prefix test
    recognised -- so every SKU keyed that way lost its memory value in
    silence. Listing the key in the doc is not the same as handling it; this
    is the test that makes the two agree.
    """
    expected = {
        "memory": [
            "Память", "память", "ПАМЯТЬ", "Памят:", "Память:", "Памяьт:",
            "памяять", "Память ", "Объем памяти", "Xotirasi", "RAM/ROM",
            # from the 2026-08-01 live recording
            "Xotira", "Xotira:", "XOTIRA", "xotra",
        ],
        "model": ["Модель", "модел"],
        "sim": ["Сим-карта", "SIM карта", " SIM карта"],
        "color": ["Цвет", "Rang"],
        # `Тип` is genuinely ambiguous and `16 PRO MAX` is a value being used
        # as a key -- neither identifies a field we read, so "other" is the
        # correct answer, not a miss.
        "other": ["Тип", "16 PRO MAX"],
    }
    for kind, keys in expected.items():
        for key in keys:
            assert _char_kind(key) == kind, f"{key!r} classified as {_char_kind(key)!r}"


def test_ram_rom_key_memory_value_reaches_name_raw():
    """The end-to-end consequence of the _char_kind gap above: a `RAM/ROM`
    key classified as "other" means the memory never reaches name_raw.
    """
    broken = payload()
    broken["data"]["makeSearch"]["items"].append({
        "catalogCard": {
            "__typename": "SkuGroupCard",
            "productId": 5555501,
            "title": "Smartfon Xiaomi Redmi Note 14, 6.7 AMOLED, 50Mp",
            "category": {"id": 15271, "title": "Smartfonlar Android"},
            "skuList": [
                {"id": 55555011, "sellPrice": 2900000, "fullPrice": 2900000,
                 "availableAmount": 3,
                 "characteristicValues": [
                     {"title": "8/256GB", "characteristic": {"title": "RAM/ROM"}},
                     {"title": "Qora", "characteristic": {"title": "Rang"}},
                 ]},
            ],
        }
    })
    by_key = {lst.source_key: lst for lst in parse(broken)}
    assert by_key["55555011"].name_raw == "Smartfon Xiaomi Redmi Note 14 8/256GB Qora"


# ---------------------------------------------------------------------------
# _build_name_raw unit tests. Arguments are (card_title, model_v, mem_v,
# color_v) exactly as _parse_sku passes them.
# ---------------------------------------------------------------------------

def test_name_raw_model_override_keeps_the_brand_not_the_noun():
    """The Critical: a `Модель` override used to destroy the name.

    Only the card head's FIRST WORD was kept as a prefix, and on uzum that
    word is very often the product-type noun "Smartfon"/"Смартфон" -- 10 of
    this recording's 20 cards lead that way. The brand was thrown away and a
    meaningless noun kept in its place. Compounding it, the section 5b
    memory strip was applied to the Модель value itself, deleting the SKU's
    own storage tier -- the one figure section 5b exists to protect. The
    pair produced "Smartfon A16 Qora": brand, RAM and storage all gone.
    """
    name = _build_name_raw(
        "Smartfon Samsung Galaxy A16, 4/128 GB, 2 SIM", "A16 8/256", "", "Qora"
    )
    assert name == "Samsung Galaxy A16 8/256 Qora"
    features = extract_features(name)
    assert features.brand == "samsung"
    assert features.ram_gb == 8
    assert features.storage_gb == 256
    # The card's own 4/128 range must not follow the SKU's 8/256 in.
    assert "4/128" not in name


def test_name_raw_iphone_card_keeps_the_brand_word_without_repeating_the_model():
    """An `IPhone`-prefixed card: the head supplies the brand the bare
    Модель value lacks, and the head words the Модель already states
    ("17", "Pro/Pro", "Max") are dropped rather than duplicated.
    """
    name = _build_name_raw(
        "IPhone 17 Pro/Pro Max, 256, 512, 1 ТБ, 2 ТБ", "17 Pro Max 256 GB", "", ""
    )
    assert name == "IPhone 17 Pro Max 256 GB"
    features = extract_features(name)
    assert features.brand == "apple"
    assert features.storage_gb == 256


def test_name_raw_recovers_memory_stated_after_the_first_comma():
    """Section 5a truncates the card title at the first comma, but two of
    this recording's 26 listings state their memory just AFTER that comma
    and carry no memory characteristic -- so both parsed to a name with no
    RAM and no storage, unkeyable, while the figure sat untouched in
    raw["card_title"]. When neither the SKU nor the truncated head yields
    memory, the full title is searched and the match appended.
    """
    name = _build_name_raw(
        "Smartfon Samsung Galaxy A16, 4/128 GB, 2 SIM, Super AMOLED, kamera 50 Mp",
        "", "", "Qora",
    )
    assert name == "Smartfon Samsung Galaxy A16 4/128 GB Qora"
    features = extract_features(name)
    assert (features.ram_gb, features.storage_gb) == (4, 128)


def test_name_raw_sku_memory_wins_over_the_cards_range():
    """docs/parsers/uzum.md section 5b, the trap that once reported
    2,672,010 for a phone whose true price was 3,068,010: the card head
    lists the range "(8+8)/128 GB", this SKU states "8/128". The card's
    figures are stripped from the head; the SKU's own value stands. The
    strip must not leave "( )/" residue behind either -- SKU 6931382 in the
    fixture parsed to "Smartfon Oppo A5i Pro ( )/ 8/128 Binafsha".
    """
    name = _build_name_raw(
        "Smartfon Oppo A5i Pro (8+8)/128 GB, oq/binafsha, IP65", "", "8/128", "Binafsha"
    )
    assert name == "Smartfon Oppo A5i Pro 8/128 Binafsha"
    assert "(" not in name and ")" not in name


def test_name_raw_keeps_a_trailing_plus_model_marker():
    """The residue cleanup strips orphaned separators, but "Pro+" is a real
    designator, not residue -- dropping the "+" merges the Pro+ into the Pro.
    """
    name = _build_name_raw(
        "Telefon Xiaomi Redmi Note 14 Pro+, 8/256GB", "Note 14 Pro+", "12/512", ""
    )
    assert name == "Xiaomi Redmi Note 14 Pro+ 12/512"


def test_name_raw_bare_sku_memory_blocks_the_card_title_recovery():
    """A bare memory figure IS a stated memory, and must switch off the
    last-resort recovery just as "8/256" does.

    _has_memory only ever recognised a slash-separated pair or a
    unit-bearing figure, so `Память: "128"` looked like NO memory at all --
    and the recovery then reached past the first comma and appended the
    card's whole RANGE beside the SKU's own correct figure. Live: card
    'Смартфон "Apple iPhone" 12, 64/128/256 ГБ, SIM' with Память "128"
    became 'Смартфон "Apple iPhone" 12 128 64/128 Алый', whose storage read
    128 while "64" became a MODEL token -- a product that does not exist.
    """
    name = _build_name_raw(
        'Смартфон "Apple iPhone" 12, 64/128/256 ГБ, SIM, чехол в подарок',
        "", "128", "Алый",
    )
    assert "64/128" not in name
    assert name == 'Смартфон "Apple iPhone" 12 128 Алый'
    features = extract_features(name)
    assert features.storage_gb == 128
    assert "64" not in features.model_tokens


def test_name_raw_bare_memory_inside_a_model_value_strips_the_card_range():
    """The same blindness on section 5b's own gate rather than the recovery.

    The strip of the card-derived prefix is gated on the SKU having stated
    memory; with `Модель: "17 Pro 256"` the figure is bare, so the gate
    never fired and the card's range survived in the prefix. Live, that
    produced 'IPhone / Max 256/512 GB 17 Pro 256 Оранжевый' -- storage 512
    from the card, "256" demoted to a model token, and three different SKUs
    (Pro 256, Pro Max 256, Pro 512) merged onto one variant.
    """
    name = _build_name_raw(
        "IPhone 17 Pro / Max 256/512 GB, E-Sim только,  Apple", "17 Pro 256", "", "Оранжевый"
    )
    assert "256/512" not in name
    features = extract_features(name)
    assert features.storage_gb == 256
    assert features.model_tokens == frozenset({"17", "pro"})


def test_name_raw_does_not_inherit_the_cards_other_bundled_model():
    """A card bundling two models must not lend the SKU the one it is not.

    'IPhone 17 Pro / Max' bundles the Pro and the Pro Max. _prefix_for_model
    dropped only the head words the Модель value already contained, so for
    the plain '17 Pro 256' SKU the word "Max" survived into the prefix and
    the offer keyed as a Pro MAX. Once a head word belongs to the model, the
    Модель value owns the rest of the head.
    """
    name = _build_name_raw(
        "IPhone 17 Pro / Max 256/512 GB, E-Sim только,  Apple", "17 Pro 256", "", "Оранжевый"
    )
    assert "Max" not in name
    assert extract_features(name).model_tokens == frozenset({"17", "pro"})

    # ...and the Pro Max SKU on the very same card still keeps its Max.
    sibling = _build_name_raw(
        "IPhone 17 Pro / Max 256/512 GB, E-Sim только,  Apple",
        "17 Pro Max 512", "", "Оранжевый",
    )
    assert extract_features(sibling).model_tokens == frozenset({"17", "pro", "max"})
    assert extract_features(sibling).storage_gb == 512


def test_name_raw_recovery_still_fires_when_the_sku_states_nothing():
    """The recovery is switched off by a STATED memory, not disabled.

    A SKU with no memory characteristic and no figure in its Модель value
    still has nothing but the card title to go on, which is the case the
    recovery was built for.
    """
    name = _build_name_raw(
        "Smartfon Samsung Galaxy A16, 4/128 GB, 2 SIM, Super AMOLED", "", "", "Qora"
    )
    assert name == "Smartfon Samsung Galaxy A16 4/128 GB Qora"


# ---------------------------------------------------------------------------
# Token handling
# ---------------------------------------------------------------------------

def test_undecodable_token_cookie_does_not_raise():
    """The JWT `exp` only decides WHEN to refresh. If uzum ever hands back an
    opaque or reformatted access_token cookie, a decode crash would kill the
    whole sweep over a token that may well still work.
    """
    exp = uzum._decode_jwt_exp("not-a-jwt")
    assert exp > 0
    assert uzum._decode_jwt_exp("") > 0


def test_401_mid_sweep_remints_once_and_retries(monkeypatch):
    """A server-side revocation is invisible to the cache, which refreshes
    only on the locally decoded `exp`. Before this, the resulting 401
    propagated an HTTPError straight out of sweep() and ended the run.
    """
    monkeypatch.setattr(uzum, "_token_cache", {"token": None, "iid": None, "exp": 0})
    mints = []

    def fake_mint():
        mints.append(1)
        return f"token-{len(mints)}", "iid"

    monkeypatch.setattr(uzum, "_mint_token", fake_mint)
    monkeypatch.setattr(uzum, "_decode_jwt_exp", lambda token: 2 ** 31)

    calls = []

    def fake_post_json(session, url, **kwargs):
        calls.append(kwargs["headers"]["Authorization"])
        if len(calls) == 1:
            response = requests.Response()
            response.status_code = 401
            raise requests.HTTPError("401 Unauthorized", response=response)
        return {"data": {"makeSearch": {"total": 0, "items": []}}}

    monkeypatch.setattr(uzum, "post_json", fake_post_json)
    source = uzum.UzumSource()
    monkeypatch.setattr(source, "_get_session", lambda: None)

    assert source._fetch_payload("Samsung", 0) == {
        "data": {"makeSearch": {"total": 0, "items": []}}
    }
    assert calls == ["Bearer token-1", "Bearer token-2"]   # re-minted, not reused


def test_second_401_is_left_to_raise(monkeypatch):
    """One retry, not a loop: a persistent 401 is a real auth failure and
    must surface rather than being swallowed into an empty sweep.
    """
    monkeypatch.setattr(uzum, "_token_cache", {"token": None, "iid": None, "exp": 0})
    monkeypatch.setattr(uzum, "_mint_token", lambda: ("token", "iid"))
    monkeypatch.setattr(uzum, "_decode_jwt_exp", lambda token: 2 ** 31)

    def always_401(session, url, **kwargs):
        response = requests.Response()
        response.status_code = 401
        raise requests.HTTPError("401 Unauthorized", response=response)

    monkeypatch.setattr(uzum, "post_json", always_401)
    source = uzum.UzumSource()
    monkeypatch.setattr(source, "_get_session", lambda: None)

    with pytest.raises(requests.HTTPError):
        source._fetch_payload("Samsung", 0)


def test_non_401_http_error_is_not_retried(monkeypatch):
    """Only 401 means "token"; a 500 must not trigger a pointless re-mint."""
    monkeypatch.setattr(uzum, "_token_cache", {"token": None, "iid": None, "exp": 0})
    mints = []

    def fake_mint():
        mints.append(1)
        return "token", "iid"

    monkeypatch.setattr(uzum, "_mint_token", fake_mint)
    monkeypatch.setattr(uzum, "_decode_jwt_exp", lambda token: 2 ** 31)

    def always_500(session, url, **kwargs):
        response = requests.Response()
        response.status_code = 500
        raise requests.HTTPError("500 Server Error", response=response)

    monkeypatch.setattr(uzum, "post_json", always_500)
    source = uzum.UzumSource()
    monkeypatch.setattr(source, "_get_session", lambda: None)

    with pytest.raises(requests.HTTPError):
        source._fetch_payload("Samsung", 0)
    assert len(mints) == 1
