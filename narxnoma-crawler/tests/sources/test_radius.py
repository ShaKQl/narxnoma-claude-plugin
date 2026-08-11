"""Offline parse tests for the radius client.

Fixture recorded live on 2026-08-11 with:
    POST https://new.api.radius.uz/graphql/
    {"query": CATEGORY_QUERY, "operationName": "CategoryProducts",
     "variables": {"slug": "konditsionery", "first": 100, "after": null}}
    Headers: Accept: application/json, Content-Type: application/json,
             Accept-Language: ru, Origin: https://radius.uz,
             Referer: https://radius.uz/,
             User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)
             AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36
"""
import json
import pathlib

import pytest

from narxnoma.sources.base import PRICE_MAX, PRICE_MIN
from narxnoma.sources.radius import _image, next_cursor, numeric_id, parse

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources"
FIXTURE = FIXTURES / "radius.json"

# A SECOND fixture, and it earns its place. `konditsionery` happens to have
# exactly one variant per product, so it cannot tell a per-product parser from
# a per-variant one -- the counts are identical. `smartfony` is where the
# distinction is real (20 products, 41 variants) and where getting it wrong
# cost 79 of 80 phone attachments. Recorded the same way with
# {"slug": "smartfony", "first": 20}.
PHONES = FIXTURES / "radius_phones.json"

# Copied from the first real node in the recorded file. The source key is the
# VARIANT id (8046), not the product id (5195) -- see radius.py.
KNOWN_SOURCE_KEY = "8046"
KNOWN_NAME = "Кондиционер Artel ARTSID2CW12BE Iceberg 12 Inv"
KNOWN_PRICE = 5_388_000
KNOWN_URL = ("https://radius.uz/ru/product/8046-"
             "konditsioner-artel-artsid2cw12be-iceberg-inv")


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def phones():
    return json.loads(PHONES.read_text(encoding="utf-8"))


def nodes(doc):
    return [e["node"] for e in doc["data"]["category"]["products"]["edges"]]


def test_fixtures_exist_and_are_not_empty():
    """Guards against every test below passing vacuously over an empty file."""
    for path in (FIXTURE, PHONES):
        assert path.exists(), f"record the fixture first: {path}"
    assert nodes(payload())
    assert nodes(phones())


def test_parse_returns_listings():
    assert parse(payload()), "parse() found nothing in a real recorded response"


def test_one_listing_per_variant_not_per_product():
    """The measured decision this client turns on.

    Emitting one listing per Product attached 1 of 80 phones (1.3%): radius
    keeps the memory pair and the colour on the variant, and a phone key
    needs both. Asserted on the PHONES fixture, because `konditsionery` has
    one variant per product and cannot tell the two parsers apart.
    """
    doc = phones()
    variants = sum(len(n["variants"]) for n in nodes(doc))
    assert variants > len(nodes(doc)), (
        "this fixture must contain multi-variant products, or the test "
        "cannot tell products from variants")
    assert len(parse(doc)) == variants == 41
    assert len(nodes(doc)) == 20


def test_the_product_name_alone_could_not_key_a_phone():
    """Why the variant is the unit, stated as a property of the data.

    Every phone product whose variants differ has a name with no memory pair;
    the variant names carry one.
    """
    import re

    memory = re.compile(r"\d+\s*/\s*\d+\s*(?:GB|ГБ)", re.I)
    multi = [n for n in nodes(phones()) if len(n["variants"]) > 1]
    assert multi
    for node in multi:
        assert not memory.search(node["name"]), node["name"]
        for variant in node["variants"]:
            assert memory.search(variant["name"]), variant["name"]


def test_the_variants_of_one_phone_keep_their_own_prices():
    """"HUAWEI Nova Y61" spans 1,397,000 to 1,959,000 across its variants. A
    per-product parser would publish one of those as the price of all three."""
    doc = phones()
    node = next(n for n in nodes(doc) if len(n["variants"]) > 1)
    listings = {x.source_key: x for x in parse(doc)}
    prices = {listings[numeric_id(v["id"])].price for v in node["variants"]}
    assert len(prices) > 1, "pick a node whose variants differ in price"


def test_every_listing_has_provenance():
    for lst in parse(payload()):
        assert lst.store_slug == "radius"
        assert lst.source_key and lst.source_key.isdigit()
        assert lst.name_raw
        assert lst.url.startswith("https://radius.uz/ru/product/")


def test_every_price_is_an_integer_inside_the_fences():
    for lst in parse(payload()):
        assert isinstance(lst.price, int)
        assert PRICE_MIN <= lst.price <= PRICE_MAX


def test_source_keys_are_unique_within_one_response():
    keys = [lst.source_key for lst in parse(payload())]
    assert len(keys) == len(set(keys))


def test_a_known_product_parses_exactly():
    lst = next(x for x in parse(payload()) if x.source_key == KNOWN_SOURCE_KEY)
    assert lst.name_raw == KNOWN_NAME
    assert lst.price == KNOWN_PRICE
    assert lst.url == KNOWN_URL
    assert lst.availability == "IN_STOCK"


def test_the_name_comes_from_the_variant_not_the_product():
    doc = payload()
    node = nodes(doc)[0]
    assert node["name"] != node["variants"][0]["name"], (
        "pick a fixture node whose variant name differs, or this proves nothing")
    lst = next(x for x in parse(doc) if x.source_key == KNOWN_SOURCE_KEY)
    assert lst.name_raw == node["variants"][0]["name"]


def test_each_variant_gets_its_own_url_and_price():
    """Verified live: /ru/product/<non-default variant id>-<slug> returns 200
    and renders that colour."""
    doc = payload()
    for node in nodes(doc):
        for variant in node["variants"]:
            vid = numeric_id(variant["id"])
            lst = next(x for x in parse(doc) if x.source_key == vid)
            assert lst.url == f"https://radius.uz/ru/product/{vid}-{node['slug']}"
            assert lst.price == int(variant["priceAmount"])


def test_the_url_never_uses_the_product_id():
    """Building it from Product.id is a clean 404 on the live site -- checked
    on six products, all 404. See radius.py's module docstring."""
    doc = payload()
    for node in nodes(doc):
        pid = numeric_id(node["id"])
        for lst in parse({"data": {"category": {"products": {
                "edges": [{"node": node}]}}}}):
            assert f"/product/{pid}-" not in lst.url


def test_a_variant_without_its_own_price_falls_back_to_the_product():
    doc = payload()
    node = nodes(doc)[0]
    node["variants"][0]["priceAmount"] = None
    lst = next(x for x in parse(doc) if x.source_key == KNOWN_SOURCE_KEY)
    assert lst.price == int(
        node["pricing"]["priceRange"]["start"]["amount"])


def test_a_product_with_no_variants_yields_nothing():
    doc = payload()
    node = nodes(doc)[0]
    before = len(parse(doc))
    dropped = len(node["variants"])
    node["variants"] = []
    assert len(parse(doc)) == before - dropped
    assert KNOWN_SOURCE_KEY not in {x.source_key for x in parse(doc)}


# --------------------------------------------------------------------------
# Saleor global ids
# --------------------------------------------------------------------------

def test_numeric_id_decodes_saleor_global_ids():
    assert numeric_id("UHJvZHVjdDo1MTk1") == "5195"              # Product:5195
    assert numeric_id("UHJvZHVjdFZhcmlhbnQ6ODA0Ng==") == "8046"  # ProductVariant:8046


def test_numeric_id_returns_none_rather_than_raising():
    """One malformed id must cost one listing, not the whole sweep."""
    for bad in (None, "", "not-base64!!", "aGVsbG8=", "UHJvZHVjdDo="):
        assert numeric_id(bad) is None


# --------------------------------------------------------------------------
# Availability and pagination
# --------------------------------------------------------------------------

def test_availability_comes_from_the_variant_and_falls_back_to_the_product():
    doc = payload()
    ns = nodes(doc)
    ns[0]["variants"][0]["isAvailable"] = False
    ns[1]["variants"][0]["isAvailable"] = None
    ns[1]["isAvailable"] = True
    out = {x.source_key: x.availability for x in parse(doc)}
    assert out[KNOWN_SOURCE_KEY] == "OUT_OF_STOCK"
    assert out[numeric_id(ns[1]["variants"][0]["id"])] == "IN_STOCK"


def test_an_unset_flag_everywhere_is_unknown_not_out_of_stock():
    doc = payload()
    node = nodes(doc)[0]
    node["isAvailable"] = None
    node["variants"][0]["isAvailable"] = None
    lst = next(x for x in parse(doc) if x.source_key == KNOWN_SOURCE_KEY)
    assert lst.availability == "UNKNOWN", (
        "an unset field is not evidence of a sold-out product")


def test_next_cursor_ends_the_sweep_when_there_is_no_next_page():
    doc = payload()
    assert doc["data"]["category"]["products"]["pageInfo"]["hasNextPage"] is False
    assert next_cursor(doc) is None


def test_next_cursor_returns_the_cursor_when_there_is_a_next_page():
    doc = payload()
    page_info = doc["data"]["category"]["products"]["pageInfo"]
    page_info["hasNextPage"] = True
    page_info["endCursor"] = "YXJyYXljb25uZWN0aW9uOjk5"
    assert next_cursor(doc) == "YXJyYXljb25uZWN0aW9uOjk5"


def test_parse_reads_the_search_connection_too():
    """search() and sweep() share parse(); the two queries differ only in
    whether the connection hangs off `category` or off the root."""
    doc = payload()
    node = nodes(doc)[0]
    search_shaped = {"data": {"products": {"edges": [{"node": node}]}}}
    assert [x.source_key for x in parse(search_shaped)] == [
        numeric_id(v["id"]) for v in node["variants"]]


def test_parse_survives_an_empty_or_missing_payload():
    assert parse({"data": {"category": None}}) == []
    assert parse({}) == []
    assert parse(None) == []


# ---------------------------------------------------------------------------
# Thumbnails radius never rendered.
#
# Saleor returns a thumbnail URL for every image, but radius's thumbnailer
# does not render .avif sources: the URL is well-formed, non-null, and 404s.
# Measured over all 274 live radius offers -- 272 thumbnails load, the 2 avif
# ones do not. Nothing upstream can catch this, because "field present" and
# "file exists" are different questions.
# ---------------------------------------------------------------------------

def test_avif_thumbnails_are_replaced_by_the_original_that_exists():
    avif = ("https://new.api.radius.uz/thumbnails/200/images/product/"
            "31101cec018f49b29871c665b6aa7fde.avif")
    assert _image({"url": avif}) == (
        "https://new.api.radius.uz/media/images/product/"
        "31101cec018f49b29871c665b6aa7fde.avif")


@pytest.mark.parametrize("url", [
    "https://new.api.radius.uz/thumbnails/200/images/product/abc.webp",
    "https://new.api.radius.uz/thumbnails/512/images/product/abc.jpg",
    "https://new.api.radius.uz/thumbnails/200/images/product/abc.png",
])
def test_every_other_format_keeps_its_thumbnail(url):
    """272 of 274 work; only avif is swapped, so a grid keeps loading renders."""
    assert _image({"url": url}) == url


def test_a_missing_thumbnail_is_none_not_a_crash():
    assert _image(None) is None
    assert _image({}) is None
    assert _image({"url": ""}) is None


def test_the_fixtures_still_parse_to_reachable_looking_images():
    for path in (FIXTURE, PHONES):
        listings = parse(json.loads(path.read_text(encoding="utf-8")))
        assert listings
        for l in listings:
            if l.image_url:
                assert l.image_url.startswith("https://new.api.radius.uz/")
                assert not (l.image_url.endswith(".avif")
                            and "/thumbnails/" in l.image_url)
