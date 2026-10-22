"""Offline parse tests for the openshop client.

Fixture recorded live on 2026-10-22 with:
    POST https://web.openshop.uz/api/v1/shop/product/get_products
         ?page=1&per_page=12&sort_by=latest&subcategory_id=4
    Headers: Accept: application/json, text/plain, */*, Accept-Language: ru,
             language: ru, Origin: https://openshop.uz, Referer: https://openshop.uz/,
             User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
             (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36
"""
import json
import pathlib

import pytest

from narxnoma.sources import openshop
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN
from narxnoma.sources.openshop import (
    CATEGORY_EXCLUDE,
    OpenshopSource,
    next_page,
    page_url,
    parse,
    title_price,
)

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "openshop.json"

# FIXTURE: copied from one real item in the recorded file.
KNOWN_SOURCE_KEY = "133328"
KNOWN_PRICE = 4268000
KNOWN_URL = "https://openshop.uz/shop/product/133328-samsung-galaxy-a27-5g-8-256gb-moviy-smartfoni?lang=ru"

# The one discounted item in the recording: Galaxy S25 FE 8/256, 8,999,000
# payable with 9,865,000 struck through.
DISCOUNTED_KEY = "112042"
DISCOUNTED_TOTAL = 8999000
DISCOUNTED_OLD = 9865000


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_exists_and_is_not_empty():
    """Guards against the parse tests passing vacuously over an empty file."""
    assert FIXTURE.exists(), f"record the fixture first: {FIXTURE}"
    assert payload()["data"]


def test_parse_returns_every_item():
    assert len(parse(payload())) == len(payload()["data"]) == 12


def test_every_listing_has_provenance():
    for lst in parse(payload()):
        assert lst.store_slug == "openshop"
        assert lst.source_key
        assert lst.name_raw
        assert lst.url.startswith("https://openshop.uz/shop/product/")


def test_every_price_is_an_integer_inside_the_fences():
    for lst in parse(payload()):
        assert isinstance(lst.price, int)
        assert PRICE_MIN <= lst.price <= PRICE_MAX


def test_source_keys_are_unique_within_one_response():
    keys = [lst.source_key for lst in parse(payload())]
    assert len(keys) == len(set(keys))


def test_known_product_parses_exactly():
    by_key = {lst.source_key: lst for lst in parse(payload())}
    assert by_key[KNOWN_SOURCE_KEY].price == KNOWN_PRICE
    assert by_key[KNOWN_SOURCE_KEY].url == KNOWN_URL
    assert by_key[KNOWN_SOURCE_KEY].availability == "IN_STOCK"


def test_price_is_the_discounted_total_not_the_struck_through_old_price():
    raw = {str(i["id"]): i for i in payload()["data"]}[DISCOUNTED_KEY]
    assert raw["price"]["old_price"] == DISCOUNTED_OLD   # the recording still shows the trap
    by_key = {lst.source_key: lst for lst in parse(payload())}
    assert by_key[DISCOUNTED_KEY].price == DISCOUNTED_TOTAL


def test_url_is_built_from_slug_never_from_the_api_link_field():
    # `link` points at web.openshop.uz -- the API host. A link built from it
    # opens the API, not the shop.
    for item, lst in zip(payload()["data"], parse(payload())):
        assert item["link"].startswith("https://web.openshop.uz/")
        assert lst.url == page_url(item["slug"])
        assert "web.openshop.uz" not in lst.url


def test_url_carries_lang_ru():
    # Without it the page renders in Uzbek ("Narx: ... so'm").
    assert page_url("x").endswith("?lang=ru")


def test_next_page_follows_the_pager_until_last_page():
    p = payload()
    assert p["meta"]["last_page"] > 1
    assert next_page(p, 1) == 2
    last = p["meta"]["last_page"]
    assert next_page({"data": [], "meta": {"last_page": last}}, last) is None


def test_an_empty_page_does_not_end_the_sweep():
    # Only the pager ends a sweep; a page whose items were all filtered is not the end.
    assert next_page({"data": [], "meta": {"last_page": 5}}, 2) == 3


@pytest.mark.parametrize("title, price", [
    (("Смартфон Honor X9d 5G 8/256GB Midnight Black | Цвет: Чёрный | Память: 8 ГБ / 256 ГБ"
      " | Цена: 4 899 000 сум"), 4899000),
    ("Apple iPhone 17 Pro Max 256GB Silver | Xotira: 12 GB / 12 GB | Narx: 17 989 000 so&#x27;m",
     17989000),
    ("Наушники | Цена: 130 000 сум", 130000),
    ("OpenShop — магазин техники", None),
])
def test_title_price_reads_both_locales(title, price):
    assert title_price(title) == price


def test_mini_ovens_are_excluded_from_ovens():
    pattern = CATEGORY_EXCLUDE["ovens"]
    for name in ("Мини-печь Premier PRM-ECO45/R", "Мини печь Premier PRM-MED45/SB", "Mini oven X"):
        assert pattern.search(name)
    for name in ("Газовая плита Premier PRM-G60-E40B", "Встраиваемая газовая панель 7TECH"):
        assert not pattern.search(name)


def test_sweep_keeps_only_the_category_subsubcategories(monkeypatch):
    items = [
        {"id": 1, "name": "Телевизор A 43", "slug": "1-a", "price": {"total": 3_000_000},
         "is_stock": True, "subsubcategory_id": 30},
        {"id": 2, "name": "Пылесос B", "slug": "2-b", "price": {"total": 1_000_000},
         "is_stock": True, "subsubcategory_id": 36},
    ]
    pages = {1: {"data": items[:1], "meta": {"last_page": 2}},
             2: {"data": items[1:], "meta": {"last_page": 2}}}
    src = OpenshopSource()
    monkeypatch.setattr(src, "_page", lambda page, **f: pages[page])
    monkeypatch.setattr(openshop, "MIN_INTERVAL", 0)
    got = list(src.sweep("televisions"))
    assert [lst.source_key for lst in got] == ["1"]
    assert got[0].category == "televisions"


def test_sweep_rejects_an_unknown_category():
    with pytest.raises(ValueError):
        list(OpenshopSource().sweep("bicycles"))
