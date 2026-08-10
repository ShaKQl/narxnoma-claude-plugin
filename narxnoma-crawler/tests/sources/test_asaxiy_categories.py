"""asaxiy's category leaves, its registration, and the pagination trap."""
import pytest

from narxnoma.matching.keys import CATEGORIES
from narxnoma.sources import SOURCES
from narxnoma.sources.asaxiy import CATEGORY_PATHS, AsaxiySource
from narxnoma.sources.base import Listing, Source
from narxnoma.pipeline.report import EXPECTED_MIN_OFFERS


def test_category_paths_cover_all_supported_categories():
    # Verified live 2026-08-10 by walking asaxiy's own category tree and
    # counting every leaf. The comment in asaxiy.py records the counts and,
    # more importantly, the three leaves deliberately NOT swept.
    assert CATEGORY_PATHS == {
        "smartphones": "telefony-i-gadzhety/telefony/smartfony",
        "televisions": "televizory-video-i-audio/televizory",
        "laptops":     "kompyutery-i-orgtehnika/noutbuki/noutbuki-2",
        "acs":         "klimaticheskaya-tehnika/kondicionery",
        "fridges":     "bytovaya-tehnika/krupnaya-tehnika-dlya-kuhni/holodilniki",
        "washers":     "bytovaya-tehnika/tehnika-dlya-doma-2/stiralnye-mashiny",
        "ovens":       "bytovaya-tehnika/krupnaya-tehnika-dlya-kuhni/gazovye-plity",
    }
    assert set(CATEGORY_PATHS) == set(CATEGORIES)


def test_asaxiy_is_registered_and_satisfies_the_source_protocol():
    # A client nothing dispatches to is a client that never runs. The harvest
    # iterates SOURCES; being importable is not the same as being wired in.
    assert "asaxiy" in SOURCES
    assert isinstance(SOURCES["asaxiy"], Source)
    assert SOURCES["asaxiy"].can_sweep is True


def test_asaxiy_has_a_coverage_floor():
    # Without a floor entry the source can silently return nothing forever:
    # that is the one failure mode pipeline/report.py exists to catch.
    assert EXPECTED_MIN_OFFERS["asaxiy"] > 0


def test_every_registered_source_has_a_coverage_floor():
    assert set(SOURCES) <= set(EXPECTED_MIN_OFFERS)


def test_asaxiy_is_seeded_in_the_schema():
    """harvest_all reports "store not seeded" for a source with no store row,
    and migration 1's seed INSERT will never run again in production."""
    import pathlib

    schema = (pathlib.Path(__file__).resolve().parents[2]
              / "narxnoma" / "db" / "schema.sql").read_text(encoding="utf-8")
    _, _, after_migration_1 = schema.partition(
        "INSERT INTO schema_version (version) VALUES (2)")
    assert "'asaxiy'" in after_migration_1, (
        "asaxiy must be seeded in an appended migration, not in the "
        "migration-1 seed list -- that INSERT is a no-op on any database "
        "that already has it")


def test_page_urls_use_a_path_segment_and_the_russian_prefix():
    src = AsaxiySource()
    path = CATEGORY_PATHS["washers"]
    assert src._url(path, 1) == f"https://asaxiy.uz/ru/product/{path}"
    assert src._url(path, 2) == f"https://asaxiy.uz/ru/product/{path}/page=2"


def test_sweep_rejects_unknown_category():
    with pytest.raises(ValueError):
        list(AsaxiySource().sweep(category="toasters"))


def _card(product_id: str, name: str, price: int = 2_000_000) -> str:
    """The minimum real markup one card needs to parse -- see test_asaxiy.py
    for the tests that run against complete recorded documents."""
    return (
        f'<div class="product__item x">'
        f'<a href="/product/p-{product_id}" '
        f'onclick="sendSelectItemEvent({product_id}, this)">x</a>'
        f'<button class="js-buy-guest">buy</button>'
        f'<span id="product_cart_data_{product_id}" data-id="{product_id}" '
        f'data-name-ru="{name}" data-price="{price}" hidden></span>'
        f'</div>'
    )


def _page(ids, total_pages: int) -> str:
    cards = "".join(_card(str(i), f"Стиральная машина Test {i}") for i in ids)
    return f"<html>{cards}<script>totalPages = parseInt('{total_pages}', 10) || 1;</script></html>"


def test_sweep_stops_at_total_pages(monkeypatch):
    import narxnoma.sources.asaxiy as mod

    fetched = []

    def fake_get_text(session, url, **kwargs):
        fetched.append(url)
        page = int(url.rsplit("page=", 1)[1]) if "page=" in url else 1
        return _page(range(page * 10, page * 10 + 3), total_pages=3)

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    src = AsaxiySource()
    src._get_session = lambda: None

    out = list(src.sweep(category="washers"))
    assert len(fetched) == 3
    assert len(out) == 9
    assert all(x.category == "washers" for x in out)


def test_sweep_survives_the_out_of_range_page_serving_page_one(monkeypatch):
    """THE trap, reproduced.

    Measured live: `stiralnye-mashiny/page=9` (of 6) does not 404 and does not
    return an empty grid -- it 301-redirects to page 1 and serves 24 real
    products again. Here totalPages is deliberately wrong (99) and every page
    returns the same three products, exactly as the redirect would. A client
    trusting totalPages alone would loop to MAX_PAGES re-ingesting page 1 and
    record a triumphant harvest of duplicates.
    """
    import narxnoma.sources.asaxiy as mod

    calls = []

    def fake_get_text(session, url, **kwargs):
        calls.append(url)
        return _page([1, 2, 3], total_pages=99)

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    src = AsaxiySource()
    src._get_session = lambda: None

    out = list(src.sweep(category="washers"))
    assert {x.source_key for x in out} == {"1", "2", "3"}
    assert len(out) == 3, "page 1 was ingested more than once"
    assert len(calls) == 2, "the sweep should stop on the first page with no new ids"


def test_sweep_applies_the_denylist(monkeypatch):
    import narxnoma.sources.asaxiy as mod

    def fake_get_text(session, url, **kwargs):
        cards = (_card("1", "Стиральная машина Bosch WGB24410ME 9 Кг")
                 + _card("2", "Сушильная машина Bosch WTN86211ME 8 Кг")
                 + _card("3", "Сушилка для белья Nika CB2"))
        return f"<html>{cards}<script>totalPages = parseInt('1', 10) || 1;</script></html>"

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    src = AsaxiySource()
    src._get_session = lambda: None

    out = list(src.sweep(category="washers"))
    assert [x.source_key for x in out] == ["1"]


def test_sweep_tags_listings_with_the_category(monkeypatch):
    import narxnoma.sources.asaxiy as mod

    def fake_paginate(fetch, parse_page, following):
        yield Listing(store_slug="asaxiy", source_key="1",
                      name_raw="Телевизор Avalon B43MQA800",
                      price=4_000_000, url="https://asaxiy.uz/product/x",
                      category="smartphones")

    monkeypatch.setattr(mod, "paginate", fake_paginate)
    src = AsaxiySource()
    src._get_session = lambda: None

    out = list(src.sweep(category="televisions"))
    assert len(out) == 1 and out[0].category == "televisions"
