"""glotr.uz parser tests.

Fixture: tests/fixtures/sources/glotr.html -- a small page built from the real
card markup (recorded live 2026-08-10), covering all three availability
modifiers (text-success / text-warning / text-danger) and the space-separated
"7 579 000 сум" price shape. The full /noutbuki/ page registers 56 cards, of
which parse keeps 50 (the rest are price-layout variants or above the fence).
"""
import pathlib

from narxnoma.matching.keys import CATEGORIES
from narxnoma.pipeline.report import EXPECTED_MIN_OFFERS
from narxnoma.sources import SOURCES
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN, Source, Listing
from narxnoma.sources.glotr import CATEGORY_PATHS, parse

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources"
FIXTURE = FIXTURES / "glotr.html"


def _page() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_fixture_exists_and_is_not_empty():
    assert FIXTURE.exists(), "record the fixture first"
    assert len(_page()) > 1000


def test_parse_returns_listings():
    out = parse(_page())
    assert len(out) == 3
    assert all(isinstance(l, Listing) for l in out)


def test_every_listing_has_provenance():
    for l in parse(_page()):
        assert l.store_slug == "glotr"
        assert l.source_key.isdigit()
        assert l.url.startswith("https://glotr.uz/")
        assert l.url.endswith(f"-p-{l.source_key}/")  # the id IS the url's tail
        assert l.name_raw
        assert l.url, "no url"


def test_every_price_is_an_integer_inside_the_fences():
    for l in parse(_page()):
        assert isinstance(l.price, int)
        assert PRICE_MIN <= l.price <= PRICE_MAX


def test_source_keys_are_unique_within_one_page():
    keys = [l.source_key for l in parse(_page())]
    assert len(keys) == len(set(keys))


def test_a_known_product_parses_exactly():
    out = {l.source_key: l for l in parse(_page())}
    l = out["1160147"]
    assert l.price == 6_048_000
    assert l.availability == "IN_STOCK"
    assert "Acer Aspire Lite" in l.name_raw
    assert l.image_url and l.image_url.startswith("https://files.glotr.uz/")


def test_availability_maps_the_modifiers():
    out = {l.source_key: l.availability for l in parse(_page())}
    assert out["1160147"] == "IN_STOCK"      # text-success
    assert out["1149800"] == "UNKNOWN"       # text-warning (под заказ)
    assert out["837435"] == "OUT_OF_STOCK"   # text-danger (нет в наличии)


def test_category_paths_cover_every_supported_category():
    # Verified live 2026-08-10: all six non-phone pages + the phones page.
    assert CATEGORY_PATHS == {
        "smartphones": "telefoni-i-plansheti",
        "televisions": "televizori",
        "laptops": "noutbuki",
        "acs": "konditsioneri",
        "fridges": "xolodilniki",
        "washers": "stiralnie-mashini",
        "ovens": "duxovie-shkafi",
    }
    assert set(CATEGORY_PATHS) == set(CATEGORIES)


def test_glotr_is_registered_and_satisfies_the_source_protocol():
    # A client nothing dispatches to is a client that never runs.
    assert "glotr" in SOURCES
    assert isinstance(SOURCES["glotr"], Source)
    assert SOURCES["glotr"].can_sweep is True


def test_glotr_has_a_coverage_floor_and_is_seeded_in_the_schema():
    assert EXPECTED_MIN_OFFERS["glotr"] > 0
    schema = (FIXTURES.parents[2] / "narxnoma" / "db" / "schema.sql").read_text(encoding="utf-8")
    _, _, after_migration_1 = schema.partition("INSERT INTO schema_version (version) VALUES (2)")
    assert "'glotr'" in after_migration_1, (
        "glotr must be seeded in an appended migration, not in the migration-1 "
        "seed list -- that INSERT is a no-op on a database that already has it")