"""glotr.uz client: another genuinely server-rendered Yii catalogue.

Like asaxiy, glotr has no public JSON API -- its pages are fully rendered
server-side (Yii framework: yii.js, yii.activeForm.js, /assets/...). A
category page (e.g. /noutbuki/) returns a complete product grid in the
initial HTML document, and pagination is a plain ``?page=N`` query
parameter. So the durable path is to parse the page.

One card, in source order (verified live 2026-08-11):

  <div class='product-card '>
    <div class='product-card__header'>
      <a href="/vstraivaemiy-...-p-881208/" class='product-card__swiper ...'>
        <div class='swiper-slide'>
          <img class='lazyload-img' src="data:image/png;base64,..."
               data-src='https://files.glotr.uz/...webp'
               alt='Встраиваемый духовой шкаф Artel Art-Classico I6701'>
        ... one more slide per extra photo ...
    <div class='product-card__content'>
      <a href='/vstraivaemiy-...-p-881208/' class='product-card__link ...'>Встраиваемый ...</a>
      <span class='text-stock text-success'>В наличии</span>
      <div class="price-retail proposal-price"> 2 610 800 <span>сум</span></div>

THE PHOTOS COME BEFORE THE NAME. That single fact is what this parser got
wrong for its whole first life: it cut each card from its *name* anchor to
the next card's name anchor, so the region it searched for an image began
after its own photos and ended inside the next card's. Every listing was
published with its NEIGHBOUR's picture -- 55 of 55 on page one of
/duxovie-shkafi/, i.e. not one image on the site was of the product it sat
under, while every count and every health check stayed green because a
present-but-wrong URL is indistinguishable from a right one in aggregate.

So a card is cut from ``<div class='product-card '``, which encloses BOTH
halves, and the product id is then read TWICE -- from the photo anchor and
from the name anchor. They must agree. When they do not, the card is dropped
rather than published: a markup shift must cost us a listing, never mint one
that pairs a real name with someone else's photograph and price.

PAGINATION -- and the second thing this parser got wrong. Past its last real
page glotr does not return an empty grid: it serves 21 unrelated products
(fridges, water coolers, sewing machines, a face-recognition controller)
under the heading "<category> - Страница N", and a DIFFERENT set every time.
The old stop was "the first page that adds no product id not already seen",
which such a page never triggers, so the sweep walked filler until MAX_PAGES
and filed all of it under whichever category it had been asked for. That is
where 2,739 "ovens" came from in a category holding 240.

The honest end-of-catalogue signal is glotr's own pager: the last real page
carries ``<li class="next disabled"><span>...</span></li>``, and filler pages
carry no ``<ul class="pagination-list">`` at all. We follow the next link and
stop when there is not one, keeping the no-new-ids rule underneath as a
backstop for the day the pager markup changes.

CATEGORIES. The phone catalogue lives under /telefoni-i-plansheti/ (phones
AND tablets) rather than a phones-only path, so the smartphones sweep applies
the shared is_phone_listing denylist to keep tablets out. The other six
categories are phones-clean category pages and need no post-filter.

ACCESS. glotr's robots.txt disallows the browse surface to every user agent.
We sweep it under an explicit grant from glotr; that permission is what makes
this client legitimate, and it is specific to this operator. Do not copy this
module's approach to another site whose robots.txt says the same thing.
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

# The card container. It opens BEFORE the photos and closes after the price,
# so a region cut here holds every field of exactly one product -- which the
# name anchor, sitting between the two, cannot do.
_RE_CARD_START = re.compile(r"<div class='product-card '")
# The photo anchor and the name anchor. Both spell the product id in their
# href as the trailing -p-<id>; parse() requires the two to agree.
_RE_PHOTO_ANCHOR = re.compile(
    r"""<a\s+href=["'](?:/[^"']*?)-p-(\d+)/["']\s+class='product-card__swiper""")
_RE_LINK = re.compile(
    r"<a\s+href='(/[^']*?-p-(\d+)/)'\s+class='product-card__link[^']*'>(.*?)</a>",
    re.S,
)
_RE_AVAIL_BLOCK = re.compile(r"<span\s+class='text-stock\s+([^']+)'>")

# glotr's entire stock vocabulary, counted live 2026-08-11 across six category
# pages: text-success "В наличии" (51), text-warning "Под заказ" (4),
# text-secondary "Уточнить наличие" (1). There is no fourth badge and no
# text-danger -- an earlier test asserted one, against a hand-written fixture
# that invented it.
#
# NOTHING HERE MAPS TO OUT_OF_STOCK, and that is the finding rather than an
# omission: glotr is a board of sellers' listings, and a seller who runs out
# delists rather than marking the card. "Под заказ" means made to order and
# "Уточнить наличие" means ask -- neither asserts the item is gone. Both were
# previously read as OUT_OF_STOCK, which hid the offer from the product page
# on the strength of a claim glotr never made. UNKNOWN keeps the offer
# visible while still barring it from setting a headline price, which only
# IN_STOCK may do.
_AVAILABILITY = {
    "text-success": "IN_STOCK",
    "text-warning": "UNKNOWN",
    "text-secondary": "UNKNOWN",
}
_RE_PRICE = re.compile(r'class="price-retail[^"]*">\s*([\d\s]+)\s*<span>сум</span>')
_RE_IMG = re.compile(r"<img class='lazyload-img'[^>]*data-src='([^']+)'")

# glotr's own pager, and the only trustworthy end-of-catalogue signal --
# see the module docstring on what lies past the last page.
_RE_PAGER = re.compile(r'<ul class="pagination-list">(.*?)</ul>', re.S)
_RE_NEXT_LINK = re.compile(r'<li class="next">\s*<a\s+href="([^"]*)"')
_RE_PAGE_NO = re.compile(r"[?&]page=(\d+)")


def next_page_number(page_html: str) -> int | None:
    """The page glotr itself links to as "next", or None at the catalogue's end.

    Three shapes, all seen live:
      * ``<li class="next"><a href="/x/?page=5" ...>`` -> 5, a real next page;
      * ``<li class="next disabled"><span>`` -> None, this is the last page
        (note the class is "next disabled", so matching bare "next" is not
        enough -- it has to be the one carrying an anchor);
      * no ``<ul class="pagination-list">`` at all -> None, and this page is
        not part of the category: past its end glotr serves unrelated goods
        under the category's heading.
    """
    pager = _RE_PAGER.search(page_html)
    if pager is None:
        return None
    link = _RE_NEXT_LINK.search(pager.group(1))
    if link is None:
        return None
    number = _RE_PAGE_NO.search(link.group(1))
    return int(number.group(1)) if number else None

# glotr's category pages are NOISY: alongside the category's own products they
# mix in unrelated listings (a парфюм/стол/микроскоп on the laptop page, a
# радиотелефон on the TV page) and accessories (a "Беспроводная мышь Lenovo"
# on the laptop page). A denylist can never catch every intruder, so this is a
# POSITIVE filter: a listing is kept only if its name carries the category's
# product-type word. Verified live 2026-08-10 against the laptop and TV pages
# (43/50 laptop names start "Ноутбук ", real TVs all carry "Телевизор"/"ТВ").
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

# Phones were the one glotr category still judged by the shared is_phone_listing
# DENYLIST, on the reasoning that its page mixes in tablets and the phone
# detector already drops those. Counted against all 442 names glotr serves
# under /telefoni-i-plansheti/, that denylist kept 245 -- among them a SanDisk
# microSD card, an HP stylus, a thermal-imaging monocular, a pyrometer, an
# Epson MFP, a GNSS receiver, prayer-bead rings, a hand warmer, a patch panel,
# a kidney supplement, a toy kitchen, bicycle racks and made-to-order shower
# cabins. A denylist enumerates what to reject, and on a classifieds board the
# things to reject are not enumerable. The other six categories learned this
# already; phones had not.
#
# So phones get the same shape as the rest: a positive keep, then the
# accessory drop, then is_phone_listing on top to take out the tablets and
# watches that DO announce themselves as phones. Measured over the same 442:
# 124 kept, and the two rules were checked separately --
#   * the noun rule keeps 120, and the 4 it drops on the accessory rule are a
#     20W charger, a Borofone holder, a MagSafe charging station and a power
#     bank, all of which name a phone without being one;
#   * the brand-first rule adds exactly 4 more, every one a real handset
#     ("Xiaomi 13 Lite 8GB+256GB Black", two Redmi Note 12 Pro Plus, a Redmi
#     12C), and adds no false positive -- it is narrow because it demands a
#     memory pair as well as a leading phone brand, which is what separates
#     "Xiaomi 13 Lite 8/256" from "Xiaomi Pad 5 6/128Gb" only in combination
#     with is_phone_listing.
_PHONE_KEEP = re.compile(r"смартфон|\biphone\b|мобильн\w{0,3}\s+телефон|\bайфон\b")
_PHONE_DROP = re.compile(
    r"держател|чехол|стекл|плёнк|пленк|зарядк|зарядн|аккумулятор|power\s*bank|пауэрбанк|"
    r"повербанк|кабель|адаптер|переходник|карта\s+памяти|стилус|наушник|гарнитур|"
    r"увеличител|лупа|подставк|кольц|ремонт|обслужив|запчаст|дисплей|экран\s+для|"
    r"сумк|рюкзак|бампер|попсокет|селфи|штатив|трипод|док-станц|автодержател|"
    r"защитн|футляр|скотч|наклейк|шлейф|батаре|корпус для|модуль|разъем|разъём|"
    # Tablets, which the brand-first rule would otherwise take: a tablet is
    # named exactly like a handset here -- brand, model, memory pair, colour.
    # Auditing the first fixed sweep, 2 of 828 kept phones were tablets
    # ("Redmi Pad 2 Pro 8/256 Grey", "Samsung X216 8/128GB Gray (Tab A9+)");
    # is_phone_listing misses both because neither says "планшет".
    r"\bpad\b|\btab\b|планшет")
# Brands whose bare "<brand> <model> <memory>" names are handsets on this page.
_PHONE_BRAND_PREFIXES = (
    "xiaomi", "samsung", "apple", "honor", "huawei", "tecno", "infinix",
    "realme", "oppo", "vivo", "redmi", "poco", "google", "oneplus",
    "nokia", "itel", "zte", "motorola", "asus",
)
# "8/128", "8GB+256GB", "3+64" -- the memory pair a handset listing carries.
_PHONE_MEMORY = re.compile(r"\b\d{1,3}\s*(?:gb|гб|г\b)?\s*[+/]\s*\d{2,4}\s*(?:gb|гб)?\b")


def _is_phone(listing: Listing) -> bool:
    """glotr's phones page announces a handset, or we do not take it."""
    low = listing.name_raw.casefold().strip()
    announced = bool(_PHONE_KEEP.search(low))
    brand_first = low.lstrip('"').startswith(_PHONE_BRAND_PREFIXES) and bool(
        _PHONE_MEMORY.search(low))
    if not (announced or brand_first):
        return False
    if _PHONE_DROP.search(low):
        return False
    return is_phone_listing(listing)


def parse(page_html: str) -> list[Listing]:
    """Turn one category page into Listings. Pure function, no I/O.

    Each card is cut at its own ``<div class='product-card '``, which opens
    before the photos and closes after the price, so every field taken from
    the region belongs to one product. The product id is then read from both
    the photo anchor and the name anchor; a card whose two ids disagree is
    dropped, because that mismatch is the exact shape of the failure this
    parser used to publish silently -- one product's name over another's
    picture.
    """
    listings: list[Listing] = []
    starts = [m.start() for m in _RE_CARD_START.finditer(page_html)]
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(page_html)
        region = page_html[start:end]

        names = _RE_LINK.findall(region)
        if len(names) != 1:
            # Zero means the template moved the name out of the card; more
            # than one means the boundary no longer separates cards. Either
            # way we no longer know which name belongs to this region.
            logger.warning("glotr: card region %d holds %d name anchors, skipping",
                           idx, len(names))
            continue
        path, pid, raw_name = names[0]
        name = re.sub(r"\s+", " ", raw_name).strip()
        if not name:
            continue

        # The id, read a second time from the photo anchor. Agreement is what
        # licenses us to take the image from this region.
        photo = _RE_PHOTO_ANCHOR.search(region)
        if photo is not None and photo.group(1) != pid:
            logger.warning("glotr: card %r carries photos for %r -- dropping the card",
                           pid, photo.group(1))
            continue

        # Price: the price-retail block inside this card's region.
        price_match = _RE_PRICE.search(region)
        price = coerce_price(price_match.group(1).replace(" ", "")) if price_match else None
        if price is None:
            # Every card has a price; a missing one is a changed template.
            logger.warning("glotr: card %r has no parseable price", pid)
            continue

        # Availability: the text-stock badge inside this card's region.
        am = _RE_AVAIL_BLOCK.search(region)
        avail = _AVAILABILITY.get(am.group(1), "UNKNOWN") if am else "UNKNOWN"

        # Image: the first slide of this card's own swiper. A card with no
        # photo anchor gets no image rather than a borrowed one.
        image_url = None
        if photo is not None:
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

        # TWO independent stops, because glotr does not answer an out-of-range
        # page with an empty grid -- it answers with 21 unrelated products
        # (see the module docstring). The primary stop is glotr's own pager;
        # the no-new-ids rule stays underneath for the day the pager markup
        # changes, so a lost end signal costs one wasted page, not a catalogue
        # of someone else's goods.
        state = {"new": 0}

        def following(page_html, page):
            if state["new"] == 0:
                logger.info("glotr %s: page %d added no new product; end of catalogue",
                            category, page)
                return None
            state["new"] = 0
            nxt = next_page_number(page_html)
            if nxt is None:
                logger.info("glotr %s: page %d is the last page its pager offers",
                            category, page)
            return nxt

        seen: set[str] = set()
        refused = 0
        for listing in paginate(fetch, parse, following):
            if listing.source_key in seen:
                continue
            seen.add(listing.source_key)
            state["new"] += 1
            # Every category is judged the same way -- a positive keep, then
            # an accessory drop. glotr is a classifieds board, so what appears
            # under a category heading is whatever a seller filed there.
            if category == "smartphones":
                keep = _is_phone(listing)
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
            logger.info("glotr %s: refused %d listings that are not %s",
                        category, refused, category)

    def search(self, query: str) -> Iterator[Listing]:
        """glotr's search is a ?text=<term> category-less page; reuse the grid parser."""
        session = self._get_session()
        page_html = get_text(session, f"{BASE_URL}/search/", params={"text": query})
        yield from parse(page_html)