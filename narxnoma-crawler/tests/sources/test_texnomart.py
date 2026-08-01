"""Offline parse tests for the texnomart client.

Fixture recorded live on 2026-07-31 with:
    GET https://gw.texnomart.uz/api/common/v1/search/result?q=smartfon&page=1&limit=20
    Headers: Accept: application/json, text/plain, */*, accept-device: web,
             accept-language: uz, accept-region: 2,
             Origin: https://texnomart.uz, Referer: https://texnomart.uz/,
             User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
             (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36
"""
import json
import pathlib

from narxnoma.matching.features import extract_features
from narxnoma.matching.keys import variant_key
from narxnoma.matching.sim import sim_kind
from narxnoma.sources.texnomart import parse
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "texnomart.json"

# FIXTURE: copy these three from one real item in the recorded file.
KNOWN_SOURCE_KEY = "354792"
KNOWN_PRICE = 1727000            # in SUM, after any unit conversion
KNOWN_URL = "https://texnomart.uz/product/detail/354792/"


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
        assert lst.store_slug == "texnomart"
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
    broken["data"]["products"].append({
        "id": 999999001,
        "name": None,
        "sale_price": 1500000,
        "old_price": 0,
    })
    broken["data"]["products"].append({
        "id": 999999002,
        "name": "Junk item with null price",
        "sale_price": None,
        "old_price": 0,
    })
    good_listings = parse(payload())
    good_keys = {lst.source_key for lst in good_listings}
    result_listings = parse(broken)   # must not raise even with the junk items above
    result_keys = {lst.source_key for lst in result_listings}
    assert good_keys <= result_keys
    assert "999999001" not in result_keys
    assert "999999002" not in result_keys
    # Neither junk item may leak through under some other key either -- pin the
    # count so a leak can't pass by coincidentally matching an existing key.
    assert len(result_listings) == len(good_listings)


def test_price_fence_drops_the_recorded_accessory():
    """Pin the one real drop in the recorded fixture, not just its count.

    The fixture holds 20 raw items but parse() yields 19. The missing one is
    id 88473, "Keramik himoya oynasi Redmi Note 9S" -- a ceramic screen
    protector priced at 4,000 SUM, well below the 100,000 SUM price fence.
    It's an accessory, not a phone, and the fence is correctly rejecting it.
    Asserting the specific key (not just a count) means this test still
    means something if the fixture is ever re-recorded and its size changes.
    """
    raw_items = payload()["data"]["products"]
    assert len(raw_items) == 20

    listings = parse(payload())
    assert len(listings) == 19

    parsed_keys = {lst.source_key for lst in listings}
    assert "88473" not in parsed_keys


def test_every_listing_yields_a_usable_identity():
    """name_raw is the clustering stage's ONLY handle on what a product is.

    See the uzum module's version of this test for why: a name that yields no
    identity is a product lost from the catalogue, silently and with every
    other test still green.

    BRAND is the non-negotiable part and texnomart meets it on all 19
    listings -- its titles lead with the brand ("OPPO Reno15 5G 12/512GB
    Aurora White Smartfoni").

    FULLY KEYABLE: 17 of 19. The two that fall short, both investigated
    rather than assumed:
      - "Vivo Y11d 4/256GB Platinum" -- "platinum" is not in COLOR_MAP, so no
        colour resolves and colour is a hard identity field. A vocabulary
        gap, not a texnomart defect: the name is well formed and every other
        field extracts.
      - "OPPO Reno15 5G 12/512GB Aurora White Smartfoni" -- brand, RAM,
        storage and colour all extract, but `model_tokens` comes out EMPTY,
        because "reno15" is 7 characters of mixed letters and digits and
        `extract_features` treats any such token of length >= 5 as an SKU
        code ("sm-a175f", "a075f") rather than a designator. Written as
        "Reno 15" the same listing keys fine. That is a matching-engine
        limitation rather than a data limitation, and it is reported as such
        -- deliberately NOT fixed here, since changing the SKU heuristic
        touches every source's identity at once.
    """
    features = [(lst, extract_features(lst.name_raw)) for lst in parse(payload())]

    brandless = [lst.name_raw for lst, f in features if not f.brand]
    assert not brandless, f"no brand recoverable, so unclusterable: {brandless}"

    keyable = [lst for lst, f in features if variant_key(f, sim_kind(lst.name_raw))]
    # Pinned to the measured value so any regression fails rather than drifts.
    assert len(keyable) == 17, [
        lst.name_raw for lst, f in features if not variant_key(f, sim_kind(lst.name_raw))
    ]
