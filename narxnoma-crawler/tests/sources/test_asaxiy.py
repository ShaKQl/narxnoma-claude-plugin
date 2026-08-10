"""Offline parse tests for the asaxiy client -- the one HTML source.

Two fixtures, recorded live on 2026-08-10, both complete unmodified documents:

  asaxiy_ru.html  GET https://asaxiy.uz/ru/product/bytovaya-tehnika/
                      tehnika-dlya-doma-2/stiralnye-mashiny/page=6
                  The LAST page of the washers category, chosen because it is
                  the page that contains out-of-stock cards: 12 in stock, 12
                  not. A first page would have proved only the happy path.

  asaxiy_uz.html  GET https://asaxiy.uz/product/bytovaya-tehnika/
                      krupnaya-tehnika-dlya-kuhni/gazovye-plity
                  The same markup served in UZBEK (`<html lang="uz">`), which
                  is what asaxiy returns by default. It is here to prove one
                  specific claim: `parse()` yields RUSSIAN names even from an
                  Uzbek page, because it reads `data-name-ru` rather than the
                  rendered title. A Russian-only fixture could not fail that
                  test, which would make it worthless.

  Headers for both: User-Agent Mozilla/5.0 (Windows NT 10.0; Win64; x64)
  AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36,
  Accept-Language: ru-RU,ru;q=0.9, Referer/Origin https://asaxiy.uz
"""
import pathlib

from narxnoma.sources.asaxiy import is_wanted, parse, total_pages
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN, Listing

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources"
RU = FIXTURES / "asaxiy_ru.html"
UZ = FIXTURES / "asaxiy_uz.html"

# Copied from one real card in asaxiy_ru.html -- the out-of-stock one, so the
# availability assertion below is anchored to a specific known product.
KNOWN_SOURCE_KEY = "71120"
KNOWN_NAME = "Стиральная машина 7TECH 7WM4S1060GSS1 6 Кг. ХИТ ПРОДАЖ!"
KNOWN_PRICE = 2_739_000
# The RUSSIAN path: asaxiy localises its own hrefs, and a stored link should
# open the page in the language the sweep read.
KNOWN_URL = "https://asaxiy.uz/ru/product/stiralnaya-mashina-7tech-7wm4s1060gss1-6-kg"


def ru():
    return RU.read_text(encoding="utf-8")


def uz():
    return UZ.read_text(encoding="utf-8")


def test_fixtures_exist_and_are_not_empty():
    """Guards against every test below passing vacuously over an empty file."""
    for path in (RU, UZ):
        assert path.exists(), f"record the fixture first: {path}"
        assert len(path.read_text(encoding="utf-8")) > 10_000


def test_parse_returns_listings():
    assert parse(ru()), "parse() found nothing in a real recorded page"


def test_parse_finds_every_card_on_the_page():
    """asaxiy serves 24 products per page and this is a full page.

    22, not 24: two cards are below PRICE_MIN and `try_build_listing` drops
    them -- laundry gel at 99,000 and anti-vibration feet at 59,000 SUM. The
    price fence turns out to be a second, independent line of defence against
    exactly the non-products the denylist below exists for. A parser that
    silently found 21 would still look fine on every other test here.
    """
    assert len(parse(ru())) == 22
    assert len(parse(uz())) == 18


def test_every_listing_has_provenance():
    # A price we cannot attribute to a specific retailer listing is worthless.
    for lst in parse(ru()):
        assert lst.store_slug == "asaxiy"
        assert lst.source_key
        assert lst.name_raw
        assert lst.url.startswith("https://asaxiy.uz/ru/product/")


def test_every_price_is_an_integer_inside_the_fences():
    for lst in parse(ru()):
        assert isinstance(lst.price, int)
        assert PRICE_MIN <= lst.price <= PRICE_MAX


def test_source_keys_are_unique_within_one_page():
    # source_key is the upsert key; duplicates would silently collapse offers.
    keys = [lst.source_key for lst in parse(ru())]
    assert len(keys) == len(set(keys))


def test_a_known_product_parses_exactly():
    lst = next(x for x in parse(ru()) if x.source_key == KNOWN_SOURCE_KEY)
    assert lst.name_raw == KNOWN_NAME
    assert lst.price == KNOWN_PRICE
    assert lst.url == KNOWN_URL


# --------------------------------------------------------------------------
# The URL belongs to THIS card. Splitting a document on a class name is only
# safe because of this check -- see the module docstring in asaxiy.py.
# --------------------------------------------------------------------------

def test_every_url_names_the_product_it_belongs_to():
    """The anchor's sendSelectItemEvent id must equal the cart block's id.

    Without this the parser would happily hand a product its NEIGHBOUR's URL
    the day asaxiy changes its card markup -- a wrong link that no price
    check, no key check and no aggregate metric could ever notice.
    """
    page = ru()
    for lst in parse(page):
        assert f"sendSelectItemEvent({lst.source_key}" in page


def test_a_card_whose_anchor_names_another_product_is_dropped():
    """Rather than emitting a listing pointing at the wrong product page."""
    page = ru()
    listing = parse(page)[0]
    tampered = page.replace(f"sendSelectItemEvent({listing.source_key}",
                            "sendSelectItemEvent(999999", 1)
    keys = {x.source_key for x in parse(tampered)}
    assert listing.source_key not in keys
    assert len(keys) == 21, "only the tampered card should have been lost"


def test_a_card_with_no_cart_block_yields_nothing():
    page = ru()
    listing = parse(page)[0]
    tampered = page.replace(f'<span id="product_cart_data_{listing.source_key}"',
                            '<span id="removed"', 1)
    assert listing.source_key not in {x.source_key for x in parse(tampered)}


# --------------------------------------------------------------------------
# Availability
# --------------------------------------------------------------------------

def test_availability_splits_the_page_the_way_the_page_reads():
    """The washers tail is half sold out; the cookers page is entirely in stock.

    A client that hard-coded one value would pass against one of these pages
    and be wrong about the whole catalogue, which is why both are asserted.
    """
    listings = parse(ru())
    assert sum(x.availability == "IN_STOCK" for x in listings) == 11
    assert sum(x.availability == "OUT_OF_STOCK" for x in listings) == 11

    cookers = parse(uz())
    assert sum(x.availability == "IN_STOCK" for x in cookers) == 18
    assert sum(x.availability == "OUT_OF_STOCK" for x in cookers) == 0


def test_the_known_out_of_stock_product_is_out_of_stock():
    lst = next(x for x in parse(ru()) if x.source_key == KNOWN_SOURCE_KEY)
    assert lst.availability == "OUT_OF_STOCK"


def test_out_of_stock_is_exactly_the_cards_that_say_so():
    """The structural signal and the rendered text must agree on every card.

    They are independent: one is a CSS class asaxiy's JavaScript binds to,
    the other is localised prose. The client reads the class precisely
    because the first attempt read a localised href and scored every Russian
    card out-of-stock -- while looking entirely reasonable.
    """
    import re

    from narxnoma.sources.asaxiy import parse as parse_page

    cards = re.split(r'(?=<div class="product__item )', ru())[1:]
    assert len(cards) == 24
    compared = 0
    for card in cards:
        listings = parse_page(card)
        if not listings:
            continue        # below the price fence; nothing to compare
        says_out = "Нет в наличии" in card
        assert (listings[0].availability == "OUT_OF_STOCK") is says_out, listings[0].name_raw
        compared += 1
    assert compared == 22, "every parsed card must have been compared"


# --------------------------------------------------------------------------
# Language
# --------------------------------------------------------------------------

def test_an_uzbek_page_still_yields_russian_names():
    """`data-name-ru` is present on the Uzbek page, and parse() prefers it.

    The recorded uz fixture renders "Shivaki 6403-E Oq elektr+gaz plitasi";
    the corpus this feeds is Russian.
    """
    listings = parse(uz())
    assert listings
    by_key = {x.source_key: x for x in listings}
    assert by_key["4146"].name_raw == "Комбинированная плита Shivaki 6403-E Белая"
    assert "plitasi" not in by_key["4146"].name_raw


def test_html_entities_in_names_are_unescaped():
    """Attribute values arrive escaped ("bug&lsquo;", "&#039;"); the matcher
    must see the same string the site renders."""
    for page in (ru(), uz()):
        for lst in parse(page):
            assert "&#0" not in lst.name_raw
            assert "&lsquo;" not in lst.name_raw
            assert "&quot;" not in lst.name_raw


# --------------------------------------------------------------------------
# Pagination -- the trap. See asaxiy.py's module docstring.
# --------------------------------------------------------------------------

def test_total_pages_is_read_from_the_page():
    assert total_pages(ru()) == 6      # washers, 144 products at 24 per page
    assert total_pages(uz()) == 1      # cookers, 18 products, a single page


def test_a_page_with_no_total_pages_marker_ends_the_sweep():
    """The safe direction: a missing end signal must stop, not walk forever
    against a paginator that answers out-of-range pages with page 1."""
    assert total_pages("<html><body>no script here</body></html>") == 1
    assert total_pages("") == 1


# --------------------------------------------------------------------------
# The category-leaf denylist
# --------------------------------------------------------------------------

def _named(name: str) -> Listing:
    return Listing(store_slug="asaxiy", source_key="1", name_raw=name,
                   price=1_000_000, url="https://asaxiy.uz/product/x")


def test_a_tumble_dryer_is_not_a_washing_machine():
    # It has a brand and a catalogue code, so it clusters perfectly -- into a
    # variant the site would render as "Стиральная машина Bosch WTN86211ME".
    assert is_wanted(_named("Сушильная машина Bosch WTN86211ME 8 Кг")) is False
    assert is_wanted(_named("Сушилка для белья Nika CB2")) is False


def test_a_washer_dryer_combo_IS_a_washing_machine():
    # The ^ anchor exists for these three. olcha and uzum already list
    # washer-dryers under `washers`; dropping asaxiy's would lose real
    # multi-store matches.
    assert is_wanted(_named("Стирально-сушильная машина Bosch WDS28460ME 8/5 Кг"))
    assert is_wanted(_named("Встраиваемая стирально-сушильная машина Bosch WKD28543EU 7 Кг"))
    assert is_wanted(_named("Стирально-сушильная машина Hofmann WM1514D7WH/HF 15/7 Кг"))


def test_services_and_licences_are_not_products():
    assert is_wanted(_named("Услуга по установке кондиционера от 24 модели")) is False
    assert is_wanted(_named('Настенный монтаж телевизора с диагональю 43"')) is False
    assert is_wanted(_named("Лицензия на операционную систему Windows 11 Home")) is False
    assert is_wanted(_named("Мобильный кронштейн AVA1500-60-1P (32″ – 75″) , Black")) is False


def test_the_denylist_keeps_every_real_product_shape():
    for name in (
        "Смартфон Samsung Galaxy A57 8/256 ГБ, Gray",
        "Телевизор Avalon B43MQA800 QLED Smart TV",
        "Ноутбук Apple MacBook Air 13 M5 16GB/512GB Midnight",
        "Кондиционер Gree Clivia Inverter 12 Black",
        "Холодильник Bosch KGN86AI32U",
        "Стиральная машина LG AIDD TW4V7EB1W 11 Кг",
        "Комбинированная плита Shivaki 6403-E Белая",
        # A Latin "X" where the Cyrillic "Х" belongs -- a real listing, and the
        # denylist must not care about spelling it cannot see.
        "Xолодильник Bosch KGN56LB31U",
    ):
        assert is_wanted(_named(name)), name


def test_the_denylist_leaves_the_recorded_pages_almost_untouched():
    """A denylist that started refusing real products would show up here.

    The cookers page is 18 cookers and nothing else, so it must lose none.
    The washers page is the TAIL of the category, where the drying racks and
    the laundry gel sit: it loses 4 of 22, and those four are named.
    """
    assert sum(is_wanted(x) for x in parse(uz())) == 18

    refused = [x.name_raw for x in parse(ru()) if not is_wanted(x)]
    assert refused == [
        "Сушилка для белья Grande Stella",
        "Сушилка для белья Magna Tenera MD-190",
        "Универсальный гель для стирки Naturea — ЭКО-формула на растительной основе, 2000 мл",
        "Сушильная машина Bosch WQG1420XME",
    ]
