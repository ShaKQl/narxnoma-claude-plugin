"""glotr.uz parser tests.

Four fixtures, all real pages recorded live 2026-08-11. The hand-written
fixture this file used to carry is gone on purpose: it asserted a
``text-danger`` stock badge that glotr does not emit, and its cards were laid
out name-first, which is precisely the layout the parser wrongly assumed. A
fixture an author invents cannot contradict the author.

  glotr.html            /duxovie-shkafi/ page 1 -- 56 cards, pager with a next
  glotr_last_page.html  /duxovie-shkafi/ page 5 -- 16 cards, "next disabled"
  glotr_past_end.html   /duxovie-shkafi/ page 6 -- no pager, 21 unrelated goods
  glotr_stock.html      /telefoni-i-plansheti/ page 1 -- all three stock badges
"""
import pathlib
import re

import pytest

from narxnoma.matching.keys import CATEGORIES
from narxnoma.pipeline.report import EXPECTED_MIN_OFFERS
from narxnoma.sources import SOURCES
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN, Listing, Source
from narxnoma.sources.glotr import (
    CATEGORY_PATHS, _DROP_RE, _KEEP_RE, _is_laptop, _is_phone, next_page_number, parse,
)

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources"


def page(name: str = "glotr.html") -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def listing(name: str, key: str = "1") -> Listing:
    return Listing(store_slug="glotr", source_key=key, name_raw=name,
                   price=1_000_000, url=f"https://glotr.uz/x-p-{key}/")


# ---------------------------------------------------------------------------
# The fixtures themselves
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["glotr.html", "glotr_last_page.html",
                                  "glotr_past_end.html", "glotr_stock.html"])
def test_fixture_exists_and_is_a_real_page(name):
    doc = page(name)
    assert len(doc) > 100_000, "record the real page, not an excerpt"
    assert "product-card__link" in doc


# ---------------------------------------------------------------------------
# Parsing one page
# ---------------------------------------------------------------------------

def test_parse_returns_one_listing_per_card():
    # 56 cards; one is dropped by the price fence (a 226,758-sum card is kept,
    # a sub-100,000 one is not), so 55 survive.
    assert len(parse(page())) == 55


def test_every_listing_has_provenance():
    for l in parse(page()):
        assert l.store_slug == "glotr"
        assert l.source_key.isdigit()
        assert l.url.startswith("https://glotr.uz/")
        assert l.url.endswith(f"-p-{l.source_key}/")  # the id IS the url's tail
        assert l.name_raw


def test_every_price_is_an_integer_inside_the_fences():
    for l in parse(page()):
        assert isinstance(l.price, int)
        assert PRICE_MIN <= l.price <= PRICE_MAX


def test_source_keys_are_unique_within_one_page():
    keys = [l.source_key for l in parse(page())]
    assert len(keys) == len(set(keys))


def test_a_known_product_parses_exactly():
    out = {l.source_key: l for l in parse(page())}
    l = out["881208"]
    assert l.name_raw == "Встраиваемый духовой шкаф Artel Art-Classico I6701 Серебристый"
    assert l.price == 2_610_800
    assert l.availability == "IN_STOCK"
    assert l.url == ("https://glotr.uz/vstraivaemiy-duxovoy-shkaf-artel-art-classico"
                     "-i6701-serebristiy-p-881208/")
    assert l.image_url == (
        "https://files.glotr.uz/company/000/005/799/products/2023/09/05/"
        "2023-09-05-14-11-41-300185-9053d6e27e7616edde3bc3af72bc0093.webp?_=ozauc")


# ---------------------------------------------------------------------------
# THE BUG THAT MADE EVERY PICTURE SOMEONE ELSE'S
#
# The photos sit before the name inside a card, so cutting cards at the name
# anchor gave each listing its NEIGHBOUR's image. Nothing downstream could see
# it: the URL was well-formed, on the right CDN, and present on every row.
# These two tests are the only thing standing between that and production.
# ---------------------------------------------------------------------------

_PHOTO_ANCHOR = re.compile(
    r"<a\s+href=\"(?:/[^\"]*?)-p-(\d+)/\"\s+class='product-card__swiper[^']*'>")
_IMG_WITH_ALT = re.compile(
    r"<img class='lazyload-img'[^>]*?data-src='([^']+)'[^>]*?alt='([^']*)'", re.S)


def _images_by_product(doc: str) -> dict[str, tuple[str | None, str | None]]:
    """Each card's own first photo, found independently of parse().

    Cut at the PHOTO anchor rather than the card container, so this agrees
    with parse() only if both are right about which photo belongs to whom.
    """
    anchors = list(_PHOTO_ANCHOR.finditer(doc))
    out: dict[str, tuple[str | None, str | None]] = {}
    for i, m in enumerate(anchors):
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(doc)
        img = _IMG_WITH_ALT.search(doc[m.start():end])
        out[m.group(1)] = ((img.group(1), img.group(2).strip()) if img else (None, None))
    return out


@pytest.mark.parametrize("name", ["glotr.html", "glotr_last_page.html",
                                  "glotr_past_end.html", "glotr_stock.html"])
def test_every_image_belongs_to_the_product_it_is_attached_to(name):
    doc = page(name)
    truth = _images_by_product(doc)
    listings = parse(doc)
    assert listings, "fixture parsed to nothing"
    for l in listings:
        assert l.image_url == truth[l.source_key][0], (
            f"{l.source_key} ({l.name_raw[:40]!r}) was given another card's photo")


def test_the_image_alt_text_names_the_same_product_as_the_card():
    """A second, independent check: glotr writes the product name into alt.

    Position agreeing with position proves little; the alt text is written by
    a different part of glotr's template, so agreement here is real evidence.
    """
    doc = page()
    truth = _images_by_product(doc)

    def plain(s: str) -> str:
        # glotr sanitises alt by blanking quotes and commas; the anchor text
        # keeps them. Compare what both spellings agree on.
        return re.sub(r"\s+", " ", s.replace('"', " ").replace(",", " ")).strip()

    checked = 0
    for l in parse(doc):
        alt = truth[l.source_key][1]
        if alt is None:
            continue
        assert plain(alt) == plain(l.name_raw), l.source_key
        checked += 1
    assert checked >= 50, "the fixture stopped carrying alt text; this test went blind"


# ---------------------------------------------------------------------------
# THE BUG THAT FILLED EVERY CATEGORY WITH SOMEONE ELSE'S GOODS
# ---------------------------------------------------------------------------

def test_next_page_follows_the_pager():
    assert next_page_number(page()) == 2


def test_the_last_real_page_ends_the_sweep():
    """"next disabled" carries no anchor -- matching bare "next" would loop."""
    doc = page("glotr_last_page.html")
    assert '<li class="next disabled">' in doc, "fixture no longer shows the end state"
    assert next_page_number(doc) is None


def test_a_page_past_the_end_ends_the_sweep():
    """Past its last page glotr serves unrelated goods, not an empty grid.

    This fixture is page 6 of a 5-page category. It holds 21 parseable
    products -- fridges, water coolers, a sewing machine -- under the heading
    "Духовые шкафы - Страница №6". The old sweep read pages like this until
    MAX_PAGES and filed all of them as ovens, which is where 2,739 "ovens"
    came from in a category holding 240.
    """
    doc = page("glotr_past_end.html")
    assert '<ul class="pagination-list">' not in doc
    assert len(parse(doc)) > 0, "the filler page is not empty -- that is the whole point"
    assert next_page_number(doc) is None


def test_sweep_stops_at_the_last_page_and_never_sees_the_filler(monkeypatch):
    import narxnoma.sources.glotr as mod
    from narxnoma.sources.glotr import GlotrSource

    pages = {1: page(), 2: page("glotr_last_page.html"), 3: page("glotr_past_end.html")}
    fetched: list[int] = []

    def fake_get_text(session, url, **kwargs):
        n = int(re.search(r"page=(\d+)", url).group(1)) if "page=" in url else 1
        fetched.append(n)
        return pages[n]

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    src = GlotrSource()
    src._get_session = lambda: None
    list(src.sweep(category="ovens"))
    assert fetched == [1, 2], "the filler page was fetched, or a real page was skipped"


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

def test_availability_maps_glotrs_three_real_badges():
    doc = page("glotr_stock.html")
    badges = set(re.findall(r"<span\s+class='text-stock\s+([^']+)'>", doc))
    assert badges == {"text-success", "text-warning", "text-secondary"}, (
        "glotr's stock vocabulary changed; re-measure _AVAILABILITY. In "
        "particular there is no text-danger badge -- the fixture this file "
        "replaced asserted one that glotr never emitted.")
    got = {l.availability for l in parse(doc)}
    assert got == {"IN_STOCK", "UNKNOWN"}


def test_nothing_on_glotr_is_reported_out_of_stock():
    """"Под заказ" and "Уточнить наличие" are not "gone" -- see _AVAILABILITY.

    OUT_OF_STOCK hides an offer from the product page entirely, so asserting
    it on a card that never said so silently deletes real listings.
    """
    for name in ("glotr.html", "glotr_last_page.html", "glotr_stock.html"):
        assert not [l for l in parse(page(name)) if l.availability == "OUT_OF_STOCK"]


# ---------------------------------------------------------------------------
# Category filters
# ---------------------------------------------------------------------------

def test_category_paths_cover_every_supported_category():
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


def test_laptop_keep_is_robust():
    assert _is_laptop("Ноутбук Acer Aspire Lite 15.6 FHD IPS, 8GB DDR5, 512GB SSD")
    assert _is_laptop("Ультрабук HP EliteBook Ultra G1i 14")
    assert _is_laptop("ASUS ROG Strix G16")
    assert _is_laptop("HP EliteBook X Flip — 2-в-1 бизнес-ноутбук")
    assert not _is_laptop("Беспроводная мышь \"Lenovo\" 400, L300")
    assert not _is_laptop("Клавиатура для ноутбука Toshiba Satellite C650")
    assert not _is_laptop("Монитор HP Series 5 23.8 inch")
    assert not _is_laptop("Моноблок Lenovo IdeaCentre AIO 24IRH9")
    assert not _is_laptop("Наушники Asus TUF GAMING H7")
    assert not _is_laptop("МФУ Canon imageRUNNER C3326i")
    assert not _is_laptop("D-Link DGS-1005A")
    assert not _is_laptop("Наросан Черника сироп с железом")
    # the user's report: repair and servicing listings filed under laptops
    assert not _is_laptop("Ремонт ноутбуков и компьютеров любой сложности")
    assert not _is_laptop("Сервисное обслуживание ноутбука ASUS")
    assert not _is_laptop("Запчасти для ноутбуков Lenovo")


def test_positive_filter_keeps_real_items_and_drops_accessories():
    tv, tvdrop = _KEEP_RE["televisions"], _DROP_RE["televisions"]
    assert tv.search("Телевизор Samsung UE55 UHD".casefold())
    assert tv.search("75\" Телевизор Hisense".casefold())
    assert not tvdrop.search("Телевизор Samsung UE55 UHD".casefold())
    assert not tv.search("Радиотелефон Panasonic KX-TG1612".casefold())
    assert not tv.search("Микроскоп Бинокулярный OPTIKA".casefold())
    assert tvdrop.search("Антенна для телевизора DigiColor".casefold())
    assert set(_KEEP_RE) == set(CATEGORIES) - {"smartphones", "laptops"}
    assert set(_DROP_RE) == set(CATEGORIES) - {"smartphones", "laptops"}


@pytest.mark.parametrize("name", [
    "Смартфон Samsung Galaxy A34 8/256GB Лавандовый",
    "iPhone 16 128GB Teal (green)",
    "Смартфон Apple iPhone 14 Pro Max 128GB Dual SIM Фиолетовый",
    # brand-first handsets, the four the noun rule alone would have lost
    "Xiaomi 13 Lite 8GB+256GB Black",
    "Redmi 12C Ocean Blue 3+64",
    "Redmi Note 12 Pro Plus 5G 8GB+256GB Midnight Black",
])
def test_phone_keep_accepts_real_handsets(name):
    assert _is_phone(listing(name))


@pytest.mark.parametrize("name", [
    # every one of these was kept as a "phone" by the old denylist
    "SanDisk Ultra microSD UHS-I 256GB — карта памяти (Class 10, до 100 МБ/с)",
    "Стилус \"HP\" RECHBL Pen USI 1 NSV EURO (Арт.- 3V1V2AA)",
    "Тепловизор-монокуляр CEM T-72",
    "Пирометр Testo 830-T4",
    "МФУ 3 в 1 Epson L3200",
    "GNSS-приемник PrinCe i90 VR",
    "Урсус - AGenYZ БАД Ursus для почек и мочевого пузыря",
    "Душевые кабины и душевые перегородки на заказ в Ташкенте | Libronic",
    "Багажники на велосипед.",
    "Детская кухня (игрушечная). Модель № 1",
    "Умное кольцо-четки ZIKR RING",
    "Рatch panel 2Е FTP cat 5e 24port",
    "Держатель для телефона на шею/ 360 градусов",
    # accessories that name a phone without being one
    "Зарядник iPhone 20W USB-C",
    "Новинка для iPhone - POWER BANK 2Е WIRELESS 10000mAh 20W BLACK!",
    "Раздвижной держатель Borofone BH24 Bright Shell для смартфона или планшета",
    # and the tablets the category is named after
    "Планшет Apple iPad Mini 7 5G 512Gb (2024)",
    "Планшет \"Xiaomi Pad 5\" 6/128Gb, Wi-Fi, (Серый)",
    "Умные часы Apple Watch SE (Gen2) 44mm",
    # Tablets named EXACTLY like handsets -- brand, model, memory pair,
    # colour, no "планшет" anywhere. These two were the only wrong rows in
    # 828 phones after the first fixed sweep, found by reading the residue
    # the brand-first rule admits. is_phone_listing does not catch either.
    "Redmi Pad 2 Pro 8/256 Grey",
    "Samsung X216 8/128GB Gray (Tab A9+)",
])
def test_phone_keep_refuses_what_the_denylist_let_through(name):
    assert not _is_phone(listing(name))


def test_the_phones_page_is_mostly_not_phones():
    """The measurement that motivates the positive rule, pinned to a fixture."""
    kept = [l for l in parse(page("glotr_stock.html")) if _is_phone(l)]
    total = len(parse(page("glotr_stock.html")))
    assert total > 30
    assert len(kept) < total / 2, (
        "if most of the phones page is now phones, re-measure the rule rather "
        "than relaxing this")


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def test_glotr_is_registered_and_satisfies_the_source_protocol():
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
