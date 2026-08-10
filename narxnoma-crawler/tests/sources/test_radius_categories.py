"""radius's category map, its registration, and the GraphQL failure modes."""
import pytest

from narxnoma.matching.keys import CATEGORIES
from narxnoma.pipeline.report import EXPECTED_MIN_OFFERS
from narxnoma.sources import SOURCES
from narxnoma.sources.base import Listing, Source
from narxnoma.sources.radius import CATEGORY_SLUGS, RadiusSource


def test_category_slugs_cover_all_supported_categories():
    # Verified live 2026-08-11 by walking radius's whole tree through
    # `categories(level: 0)` and reading every totalCount.
    assert CATEGORY_SLUGS == {
        "smartphones": ("smartfony", "iphone-17-17-pro-17-pro-max-air", "iphone-air-3"),
        "televisions": ("televizory",),
        "laptops": ("noutbuki", "noutbuki-apple"),
        "acs": ("konditsionery",),
        "fridges": ("kholodilniki",),
        "washers": ("stiralnye-mashiny",),
        "ovens": ("gazovye-plity", "dukhovoi-shkaf"),
    }
    assert set(CATEGORY_SLUGS) == set(CATEGORIES)


def test_apple_products_are_swept_separately():
    """The trap this map exists for.

    radius files MacBooks and iPhones under a top-level "Apple" category, not
    under `noutbuki`/`smartfony`. Sweeping the obvious slug alone silently
    loses every Apple product -- including the iPhones, which are the
    most-compared phones in the catalogue, and whose absence looks exactly
    like a retailer that stopped selling them.
    """
    assert "noutbuki-apple" in CATEGORY_SLUGS["laptops"]
    assert any("iphone" in s for s in CATEGORY_SLUGS["smartphones"])


def test_radius_is_registered_and_satisfies_the_source_protocol():
    assert "radius" in SOURCES
    assert isinstance(SOURCES["radius"], Source)
    assert SOURCES["radius"].can_sweep is True


def test_radius_has_a_coverage_floor():
    assert EXPECTED_MIN_OFFERS["radius"] > 0


def test_every_registered_source_has_a_coverage_floor():
    assert set(SOURCES) <= set(EXPECTED_MIN_OFFERS)


def test_radius_is_seeded_in_the_schema():
    """harvest_all reports "store not seeded" for a source with no store row,
    and the migration-1 seed INSERT will never run again in production."""
    import pathlib

    schema = (pathlib.Path(__file__).resolve().parents[2]
              / "narxnoma" / "db" / "schema.sql").read_text(encoding="utf-8")
    _, _, appended = schema.partition(
        "INSERT INTO schema_version (version) VALUES (2)")
    assert "'radius'" in appended


def test_sweep_rejects_unknown_category():
    with pytest.raises(ValueError):
        list(RadiusSource().sweep(category="toasters"))


# --------------------------------------------------------------------------
# GraphQL reports failure with HTTP 200 and an `errors` key -- the uzum trap.
# --------------------------------------------------------------------------

def _node(pid_b64: str, name: str, variant_b64: str, price: int = 3_000_000):
    return {"node": {
        "id": pid_b64, "name": name, "slug": "x", "isAvailable": True,
        "brand": {"name": "Artel"}, "category": {"slug": "konditsionery"},
        "defaultVariant": {"id": variant_b64},
        "variants": [{"id": variant_b64, "name": name, "sku": "X",
                      "priceAmount": price, "currency": "UZS",
                      "isAvailable": True, "quantityAvailable": 5,
                      "thumbnail": {"url": "https://new.api.radius.uz/t.webp"}}],
        "pricing": {"priceRange": {"start": {"amount": price, "currency": "UZS"}}},
        "thumbnail": {"url": "https://new.api.radius.uz/t.webp"},
    }}


def _page(edges, has_next=False, cursor=None):
    return {"data": {"category": {"slug": "konditsionery", "products": {
        "totalCount": len(edges),
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
        "edges": edges}}}}


def test_a_graphql_errors_key_raises_rather_than_yielding_nothing(monkeypatch):
    """HTTP 200 with an `errors` key is how GraphQL reports failure. Swallowing
    it would record a half-swept category as a successful harvest of nothing --
    the one failure mode EXPECTED_MIN_OFFERS and harvest_run.ok exist to catch.
    """
    import narxnoma.sources.radius as mod

    monkeypatch.setattr(mod, "post_json", lambda *a, **k: {
        "errors": [{"message": "Cannot query field \"gross\" on type \"Money\"."}]})
    src = RadiusSource()
    src._get_session = lambda: None
    with pytest.raises(ValueError, match="GraphQL errors"):
        list(src.sweep(category="acs"))


def test_an_unknown_slug_raises_rather_than_yielding_nothing(monkeypatch):
    import narxnoma.sources.radius as mod

    monkeypatch.setattr(mod, "post_json", lambda *a, **k: {"data": {"category": None}})
    src = RadiusSource()
    src._get_session = lambda: None
    with pytest.raises(ValueError, match="no such category"):
        list(src.sweep(category="acs"))


def test_sweep_walks_the_cursor_to_the_end(monkeypatch):
    import narxnoma.sources.radius as mod

    pages = [
        _page([_node("UHJvZHVjdDox", "A", "UHJvZHVjdFZhcmlhbnQ6MTE=")],
              has_next=True, cursor="c1"),
        _page([_node("UHJvZHVjdDoy", "B", "UHJvZHVjdFZhcmlhbnQ6MjI=")]),
    ]
    seen_cursors = []

    def fake_post(session, url, json=None, **kw):
        seen_cursors.append(json["variables"]["after"])
        return pages[len(seen_cursors) - 1]

    monkeypatch.setattr(mod, "post_json", fake_post)
    src = RadiusSource()
    src._get_session = lambda: None

    out = list(src.sweep(category="acs"))
    # source_key is the VARIANT id: ProductVariant:11 and ProductVariant:22.
    assert [x.source_key for x in out] == ["11", "22"]
    assert seen_cursors == [None, "c1"], "the endCursor must be carried forward"
    assert all(x.category == "acs" for x in out)


def test_sweep_deduplicates_a_product_reached_through_two_slugs(monkeypatch):
    """`ovens` and `laptops` sweep two slugs each, and Saleor's
    Category.products includes descendants -- so the same product can arrive
    twice. source_key is the upsert key, so a duplicate would inflate
    HarvestResult.seen while writing one row."""
    import narxnoma.sources.radius as mod

    same = _node("UHJvZHVjdDo5", "Duxovka", "UHJvZHVjdFZhcmlhbnQ6OTk=")
    monkeypatch.setattr(mod, "post_json", lambda *a, **k: _page([same]))
    src = RadiusSource()
    src._get_session = lambda: None

    out = list(src.sweep(category="ovens"))     # two slugs, one product each
    assert [x.source_key for x in out] == ["99"]


def test_sweep_tags_listings_with_our_category(monkeypatch):
    import narxnoma.sources.radius as mod

    def fake_paginate(fetch, parse_page, following):
        yield Listing(store_slug="radius", source_key="1",
                      name_raw="Телевизор Artel UA43H3502",
                      price=4_000_000, url="https://radius.uz/ru/product/1-x",
                      category="smartphones")

    monkeypatch.setattr(mod, "paginate", fake_paginate)
    src = RadiusSource()
    src._get_session = lambda: None
    out = list(src.sweep(category="televisions"))
    assert len(out) == 1 and out[0].category == "televisions"
