"""glotr.uz client: another genuinely server-rendered Yii catalogue.

Like asaxiy, glotr has no public JSON API -- its pages are fully rendered
server-side (Yii framework: yii.js, yii.activeForm.js, /assets/...). A
category page (e.g. /noutbuki/) returns a complete product grid in the
initial HTML document, and pagination is a plain ``?page=N`` query
parameter. So the durable path is to parse the page.

The card structure, verified live 2026-08-10:

  <a href='/noutbuk-acer-gadget-etbook-14-2k-...-p-1153574/'
     class='product-card__link text-overflow-two-line'>Ноутбук Acer Gadget ...</a>
      ^ the product id is the trailing ``-p-<id>`` in the URL
  <span class='text-stock text-success'>В наличии</span>      (in stock)
  <span class='text-stock text-warning'>Под заказ</span>      (on order)
  <div class="price-retail proposal-price"> 7 579 000 <span>сум</span></div>
  <img class='lazyload-img' ... data-src='https://files.glotr.uz/...jpg'>

Price is rendered with space thousands-separators plus a currency word
("7 579 000 сум"); we strip spaces and run it through coerce_price, never
trusting the raw string. Availability is mapped from the modifier class
(text-success -> IN_STOCK, text-warning -> UNKNOWN, anything else ->
OUT_OF_STOCK). The image is the lazyload data-src (the src is a transparent
1x1 placeholder).

PAGINATION. ``?page=N`` walks 1..last_page; a page beyond the end returns an
empty grid (no redirect loop like asaxiy's). We stop on the first page that
contributes no product id not already seen -- the same second stop as axaxiy,
so a change in the total-pages presentation can never turn into a duplicate
ingest loop.

CATEGORIES. The phone catalogue lives under /telefoni-i-plansheti/ (phones
AND tablets) rather than a phones-only path, so the smartphones sweep applies
the shared is_phone_listing denylist to keep tablets out. The other six
categories are phones-clean category pages and need no post-filter.
"""
import logging
import re
from dataclasses import replace
from typing import Iterator

from narxnoma.sources.base import Listing, coerce_price, paginate, try_build_listing
from narxnoma.sources.http import get_text, polite_session
from narxnoma.sources.not_a_phone import is_phone_listing

logger = logging.getLogger(__name__)

BASE_URL = "https://glotr.uz"

# category -> glotr category path (verified live 2026-08-10).
CATEGORY_PATHS = {
    "smartphones": "telefoni-i-plansheti",
    "televisions": "televizori",
    "laptops": "noutbuki",
    "acs": "konditsioneri",
    "fridges": "xolodilniki",
    "washers": "stiralnie-mashini",
    "ovens": "duxovie-shkafi",
}

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

# The product card: anchor with the human name; the id is the -p-<id> suffix.
_RE_CARD = re.compile(
    r"<a\s+href='(/[^']*?-p-(\d+)/)'\s+class='product-card__link[^']*'>(.*?)</a>",
    re.S,
)
_RE_AVAIL = re.compile(
    r"<span\s+class='text-stock\s+([^']+)'>\s*(?:В наличии|Под заказ|Нет в наличии|Нет в наличии\s*)?\s*</span>"
)
_RE_AVAIL_BLOCK = re.compile(r"<span\s+class='text-stock\s+([^']+)'>")
_RE_PRICE = re.compile(r'class="price-retail[^"]*">\s*([\d\s]+)\s*<span>сум</span>')
_RE_IMG = re.compile(r"<img class='lazyload-img'[^>]*data-src='([^']+)'")

# glotr's category pages are NOISY: alongside the category's own products they
# mix in unrelated listings (a парфюм/стол/микроскоп on the laptop page, a
# радиотелефон on the TV page) and accessories (a "Беспроводная мышь Lenovo"
# on the laptop page). A denylist can never catch every intruder, so this is a
# POSITIVE filter: a listing is kept only if its name carries the category's
# product-type word. Verified live 2026-08-10 against the laptop and TV pages
# (43/50 laptop names start "Ноутбук ", real TVs all carry "Телевизор"/"ТВ").
# The smartphones sweep uses is_phone_listing instead (its category mixes
# tablets, and the phone detector already drops them).
_KEEP_RE = {
    "televisions": re.compile(r"телевизор|smart\s*tv|led\s*tv|\bтв\b|\btv\b"),
    "acs":         re.compile(r"кондиционер|сплит[- ]систем"),
    "fridges":     re.compile(r"холодильник|морозильн|винный шкаф"),
    "washers":     re.compile(r"стиральн"),
    "ovens":       re.compile(r"духов|газовая плита|электроплита|вытяжк|варочн"),
}

# Laptops are the messiest glotr category: names are inconsistent ("Ноутбук
# Acer…" vs bare "ASUS ROG Strix G16" vs "HP EliteBook — бизнес-ноутбук"),
# and non-laptops leak in (monitors, headphones, AIOs, printers, network
# gear, mice, keyboards). A startswith check is too strict (drops real
# brand-first laptops); a bare contains-check keeps "Клавиатура для ноутбука".
# So: keep a laptop iff (it carries the word "ноутбук" OR starts with a known
# laptop brand) AND its name does not signal a NON-laptop product/accessory.
_LAPTOP_BRAND_PREFIXES = (
    "asus", "lenovo", "hp ", "acer", "dell", "msi", "apple", "samsung",
    "huawei", "xiaomi", "toshiba", "gigabyte", "razer", "honor", "vivo ",
    "realme", "infinity", "irbis", "depo", "prestigio", "thunderobot",
)
_LAPTOP_DROP = re.compile(
    r"монитор|моноблок|наушник|гарнитур|принтер|сканер|мфу|свитч|коммутатор|роутер|маршрутизатор|"
    r"планшет|приставк|консоль|проектор|мыш|клавиатур|сумк|чехол|подставк|аккумулятор|блок питания|"
    r"зарядн|зарядк|кабель|адаптер|переходник|охлажд|коврик|флеш|док-станц|док станц|веб-камер|колонк|"
    r"микрофон|динамик|аккустик|павербанк|повербанк|разветвит|хаб|держател|экран для|запчаст|ремонт|"
    r"обслуживан|корпус|термопаст|вентилятор|кулер для|наручные|ссд|backpack|рюкзак|ink[- ]tank|printer"
)


def _is_laptop(name: str) -> bool:
    low = name.casefold().strip()
    has_laptop_word = "ноутбук" in low or "нетбук" in low or "ультрабук" in low or "макбук" in low
    brand_prefix = low.startswith(_LAPTOP_BRAND_PREFIXES)
    return (has_laptop_word or brand_prefix) and not _LAPTOP_DROP.search(low)

# A positive keep isn't enough: an accessory is often named "<thing> для
# ноутбука" and so carries the product-type word. This is the OTHER half --
# reject names that are accessories/spares/consumables for the category's
# device. Combined test: keep iff _KEEP_RE matches AND _DROP_RE does not.
# (laptops is startswith-based in sweep(), so it has no regex here.)
_DROP_RE = {
    "televisions": re.compile(
        r"антенн|кронштейн|пульт|подставк|кабель|тюнер|ресивер|креплени|держател|стенд|шкив|крючок|запчаст|ремонт"),
    "acs": re.compile(
        r"кронштейн|монтаж|установ|заправ|фреон|чистк|обслужив|пульт|дренаж|провод|запчаст|ремонт"),
    "fridges": re.compile(
        r"термометр|уплотнитель|полк|набор|органайзер|контейнер|кулер для воды|чистк|средство|запчаст|ремонт"),
    "washers": re.compile(
        r"порошок|средство|капсул|гель для|сетк|мешок|кондиционер для белья|смягчитель|чистк|запчаст|ремонт"),
    "ovens": re.compile(
        r"противень|форма|перчатк|рукавиц|щетк|средство|решетк|сковород|чистк|набор|запчаст|ремонт"),
}


def parse(page_html: str) -> list[Listing]:
    """Turn one category page into Listings. Pure function, no I/O.

    Cards are matched by their product-card__link anchor; the product id is
    the ``-p-<id>`` suffix of that same href, so a shifted card boundary can
    never pair a name with a neighbour's id (the id comes from the same
    anchor the name does).
    """
    listings: list[Listing] = []
    cards = list(_RE_CARD.finditer(page_html))
    for idx, m in enumerate(cards):
        path, pid, name = m.group(1), m.group(2), m.group(3)
        name = re.sub(r"\s+", " ", name).strip()
        if not name or not pid:
            continue
        # Everything that belongs to THIS card lies between its anchor and the
        # next card's anchor (or the end of the page for the last one).
        region_end = cards[idx + 1].start() if idx + 1 < len(cards) else len(page_html)
        region = page_html[m.start():region_end]

        # Price: the price-retail block inside this card's region.
        price_match = _RE_PRICE.search(region)
        price = coerce_price(price_match.group(1).replace(" ", "")) if price_match else None
        if price is None:
            # Every card has a price; a missing one is a changed template.
            logger.warning("glotr: card %r has no parseable price", pid)
            continue

        # Availability: the text-stock modifier inside this card's region.
        avail = "OUT_OF_STOCK"
        am = _RE_AVAIL_BLOCK.search(region)
        if am:
            modifier = am.group(1)
            if modifier == "text-success":
                avail = "IN_STOCK"
            elif modifier == "text-warning":
                avail = "UNKNOWN"  # "под заказ" -- not physically in stock

        # Image: the lazyload data-src inside this card's region.
        image_url = None
        im = _RE_IMG.search(region)
        if im:
            image_url = im.group(1)

        listing = try_build_listing(
            store_slug="glotr",
            source_key=pid,
            name_raw=name,
            price=price,
            url=f"{BASE_URL}{path}",
            availability=avail,
            image_url=image_url,
        )
        if listing is not None:
            listings.append(listing)
    return listings


class GlotrSource:
    slug = "glotr"
    can_sweep = True

    def __init__(self) -> None:
        self._session = None

    def _get_session(self):
        if self._session is None:
            self._session = polite_session(
                referer=f"{BASE_URL}/",
                origin=BASE_URL,
                extra_headers=_HEADERS,
            )
        return self._session

    def _url(self, path: str, page: int) -> str:
        url = f"{BASE_URL}/{path}/"
        return url if page <= 1 else f"{url}?page={page}"

    def sweep(self, category: str = "smartphones") -> Iterator[Listing]:
        """Every item in one glotr category, walking ?page=N to the end."""
        path = CATEGORY_PATHS.get(category)
        if path is None:
            raise ValueError(f"unknown category {category!r}")
        session = self._get_session()

        def fetch(page):
            return get_text(session, self._url(path, page))

        # Stop on the first page that adds no new product id -- the same
        # out-of-range/end guard as asaxiy, so a wrong total-pages hint can
        # never re-ingest page 1 forever.
        state = {"new": 0}

        def following(page_html, page):
            if state["new"] == 0:
                logger.info("glotr %s: page %d added no new product; end of catalogue",
                            category, page)
                return None
            state["new"] = 0
            return page + 1

        seen: set[str] = set()
        refused = 0
        for listing in paginate(fetch, parse, following):
            if listing.source_key in seen:
                continue
            seen.add(listing.source_key)
            state["new"] += 1
            # The phone category is /telefoni-i-plansheti/ (phones+tablets);
            # keep only genuine phones there. Other categories are noisy too
            # (accessories + unrelated goods), so keep only names that carry
            # the category's product-type word.
            if category == "smartphones":
                keep = is_phone_listing(listing)
            elif category == "laptops":
                # glotr names laptops inconsistently ("Ноутбук Acer…" vs bare
                # "ASUS ROG Strix G16"); _is_laptop keeps real laptops and
                # drops the mice/keyboards/monitors that leak into the page.
                keep = _is_laptop(listing.name_raw)
            else:
                name = listing.name_raw.casefold()
                keep_re = _KEEP_RE.get(category)
                drop_re = _DROP_RE.get(category)
                keep = (keep_re is not None and bool(keep_re.search(name))
                        and not (drop_re is not None and drop_re.search(name)))
            if not keep:
                refused += 1
                continue
            if listing.category != category:
                listing = replace(listing, category=category)
            yield listing
        if refused:
            logger.info("glotr: refused %d non-phone listings in the phones sweep", refused)

    def search(self, query: str) -> Iterator[Listing]:
        """glotr's search is a ?text=<term> category-less page; reuse the grid parser."""
        session = self._get_session()
        page_html = get_text(session, f"{BASE_URL}/search/", params={"text": query})
        yield from parse(page_html)