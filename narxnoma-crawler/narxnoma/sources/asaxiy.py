"""asaxiy.uz client: the one source that is genuinely server-rendered HTML.

docs/parsers/README.md opens with "None of these sites can be scraped from
HTML -- every one is a JavaScript SPA that renders an empty shell." asaxiy is
the exception, and the exception is load-bearing here: it has **no public JSON
API at all**. Probed live 2026-08-10, the only `/ajax/*` endpoints its own
frontend calls are `check-phone`, `login-validate`, `send-verification-sms`
and `new-filter-url` -- account and filter plumbing, no catalogue. Its category
pages return a complete, fully-populated product grid in the initial HTML
document, and its "show more" button re-requests that same URL. So the
durable path for THIS retailer is the inverse of the rule: parse the page.

Three things make that safe rather than fragile, and each is asserted by a
test against a recorded page:

1. **The identity is not scraped from prose.** Every card carries a hidden
   `<span id="product_cart_data_<id>">` whose data-attributes are the same
   values asaxiy's own cart uses: `data-id`, `data-name`, `data-name-ru`,
   `data-price`, `data-old-price`, `data-img`, `data-brand-name`. We read
   those, not the rendered price text ("6 719 000 so'm") -- no thousands
   separators, no currency word, no locale to get wrong.
2. **The product URL is tied to the product id.** The card's anchor is
   `<a href="/product/<slug>" onclick="sendSelectItemEvent(<id>, this)">`, and
   the parser requires that id to equal the cart block's id. A card boundary
   that ever shifted would therefore produce no listing rather than a listing
   with a neighbour's URL -- the failure mode that matters when splitting a
   document on a class name.
3. **Russian is requested by path, not by cookie.** See LANGUAGE below.

THE PAGINATION TRAP, measured live: a page number beyond the end does not
404 and does not return an empty grid -- it **301-redirects to page 1 and
serves 24 real products again**. `stiralnye-mashiny/page=9` (of 6 pages)
returned 24 cards. A client that stopped on "an empty page" would loop
forever re-ingesting page 1 and record a triumphant harvest of duplicates.
The end of the catalogue is `totalPages`, which every full page states in
its own inline script (`let totalPages = parseInt('6', 10) || 1;`), and
`sweep()` additionally stops the moment a page contributes no product id it
has not already seen. Two independent stops for one trap, because the
failure is silent.

LANGUAGE. The corpus is Russian; asaxiy defaults to Uzbek (`<html lang="uz">`).
Neither the `_language` cookie nor `Accept-Language` changes that -- both were
tried and both returned Uzbek titles. `?language=ru` works, but only because
it 301s to the canonical `/ru/product/...` path, and that redirect is dropped
when the request carries `X-Requested-With: XMLHttpRequest`. So this client
requests the `/ru/` path directly: stateless, no cookie jar to keep warm, no
redirect to survive. `parse()` still prefers `data-name-ru` over `data-name`,
which means it yields Russian names even from an Uzbek page -- belt and
braces, and testable against a fixture recorded either way.

WHY FULL PAGES AND NOT THE LIGHTER FRAGMENT. Sending `X-Requested-With:
XMLHttpRequest` gets the bare product grid (~310 KB instead of ~800 KB), which
is tempting. It also drops the `totalPages` script -- the only end-of-
catalogue signal there is, against a paginator that answers out-of-range
pages with page 1. Trading the stop condition for bandwidth is not a trade.
Our largest category is 10 pages.
"""
import html as html_module
import logging
import re
from dataclasses import replace
from typing import Iterator

from narxnoma.sources.base import Listing, coerce_price, paginate, try_build_listing
from narxnoma.sources.http import get_text, polite_session

logger = logging.getLogger(__name__)

BASE_URL = "https://asaxiy.uz"
# The Russian catalogue path. Page 1 has no suffix; page N >= 2 appends
# "/page=N" as a PATH segment, not a query parameter (asaxiy's own pagination
# links and its "show more" button both use this form).
CATEGORY_URL = BASE_URL + "/ru/product/{path}"

# category -> asaxiy leaf category path, verified live 2026-08-10 by walking
# the full category tree off /product/bytovaya-tehnika and counting each leaf:
#
#   smartphones   233 items / 10 pages
#   televisions    57 items /  3 pages
#   laptops        90 items /  4 pages
#   acs           113 items /  5 pages
#   fridges       107 items /  5 pages
#   washers       132 items /  6 pages
#   ovens          18 items /  1 page
#
# Leaves deliberately NOT swept, each checked rather than assumed:
#
#   .../kuhnya/mikrovolnovye-i-duhovye-pechi -- reads like the oven category
#   and is not one. All 120 of its listings were read: 91 microwaves, 29
#   mini-ovens, and ZERO built-in ovens. Meanwhile all 540 `ovens` offers the
#   other six sources have contributed contain no microwave at all. Sweeping
#   it would add a product type no other retailer files under `ovens`, so
#   nothing could ever price-compare, and every one would render under the
#   "Духовой шкаф" label. asaxiy simply does not sell built-in ovens.
#
#   .../kuhnya/nastolnye-plity -- 3 items, tabletop hotplates (Sonifer
#   SF-3050, BQ HP124SS). A countertop hob is not the freestanding cooker the
#   other sources list under `ovens`.
#
#   .../noutbuki (the parent) -- carries laptop BAGS, stands, docks and
#   chargers as siblings of the machines. `noutbuki-2` is the leaf that holds
#   only laptops.
CATEGORY_PATHS = {
    "smartphones": "telefony-i-gadzhety/telefony/smartfony",
    "televisions": "televizory-video-i-audio/televizory",
    "laptops":     "kompyutery-i-orgtehnika/noutbuki/noutbuki-2",
    "acs":         "klimaticheskaya-tehnika/kondicionery",
    "fridges":     "bytovaya-tehnika/krupnaya-tehnika-dlya-kuhni/holodilniki",
    "washers":     "bytovaya-tehnika/tehnika-dlya-doma-2/stiralnye-mashiny",
    "ovens":       "bytovaya-tehnika/krupnaya-tehnika-dlya-kuhni/gazovye-plity",
}

_HEADERS = {
    # A catalogue page, not JSON -- polite_session's default Accept would be
    # a lie about what this client wants.
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

# One product card starts here. Splitting a document on a class name is only
# safe because nothing downstream trusts the split alone: a card that does not
# also contain a cart block AND an anchor whose sendSelectItemEvent id matches
# that block yields no listing at all.
_CARD_BOUNDARY = re.compile(r'(?=<div class="product__item )')

# The hidden block asaxiy's own add-to-cart reads. Machine-generated, one per
# card, and the source of every field except the URL.
_CART_DATA = re.compile(r'<span id="product_cart_data_(?P<id>\d+)"(?P<attrs>.*?)hidden>', re.S)
_ATTR = re.compile(r'data-([a-z\-]+)="(?P<value>[^"]*)"')

# The product link, and the assertion that it belongs to this card. The `/ru`
# segment is optional because asaxiy localises its own hrefs: the Uzbek page
# links to /product/<slug>, the Russian one to /ru/product/<slug>. Whichever
# it gives us is what we store, so a stored link opens the page in the
# language the sweep read.
_PRODUCT_LINK = re.compile(
    r'<a\s+href="(?P<path>(?:/ru)?/product/[^"?#]+)"\s+'
    r'onclick="sendSelectItemEvent\((?P<id>\d+)')

# Structural, language-independent stock signal: an in-stock card renders the
# buy control, an out-of-stock one renders "● Нет в наличии" instead.
# Measured on the whole washers category (144 cards): 132 carried the control
# and 12 did not, and the 12 were exactly the 12 carrying the out-of-stock
# text -- no card had both and none had neither.
#
# The CLASS, not the button's href, and not the text. The href is localised
# (`/cart/simple?slug=` on an Uzbek page, `/ru/cart/simple?slug=` on a Russian
# one) -- reading it cost a first attempt that scored every Russian card
# out-of-stock while looking perfectly reasonable. The text is localised too.
# `js-buy-guest` is the hook asaxiy's own JavaScript binds to, identical on
# both language paths.
_ADD_TO_CART = "js-buy-guest"

# `let totalPages = parseInt('6', 10) || 1;` -- see the module docstring. This
# is the ONLY end-of-catalogue signal; an out-of-range page serves page 1.
_TOTAL_PAGES = re.compile(r"totalPages\s*=\s*parseInt\('(\d+)'")

# Things asaxiy files inside a product category that are not that product.
# Its leaves are broader than the other six retailers': `stiralnye-mashiny`
# holds tumble dryers, drying racks, stacking kits and laundry gel alongside
# the washing machines, and `televizory` holds wall-mounting SERVICES.
#
# This matters more than the usual "search returned an accessory", because
# these DO form keys. "Сушильная машина Bosch WTN86211ME" has a brand and a
# catalogue code, so it clusters perfectly -- into a variant the site then
# renders as "Стиральная машина Bosch WTN86211ME". A tumble dryer labelled a
# washing machine is not a coverage gap, it is a wrong page.
#
# A DENYLIST, not an allowlist, for the reason not_a_phone.py gives: asaxiy's
# titles are template-generated and noun-led today ("Смартфон Xiaomi ...",
# 233 of 233), and an allowlist would silently drop the whole category the
# day that template changes. Earned by reading all 769 live titles across the
# seven swept leaves on 2026-08-10: it drops 76 (9.9%), every one of them
# genuinely not the category's product, and drops nothing real.
#
# The ^ anchor is load-bearing on one entry. "Сушильная машина" at the START
# is a tumble dryer; "Стирально-сушильная машина" and "Встраиваемая стирально-
# сушильная машина" are washer-dryer COMBOS -- washing machines, which olcha
# and uzum already list under `washers`. Anchoring keeps the combos.
_WRONG_PRODUCT = re.compile(
    r"^\s*("
    r"услуг\w*|установк\w*|монтаж\w*|настенный\s+монтаж|"
    r"лицензи\w*|официальн\w+\s+лицензионн\w*|"
    r"кронштейн\w*|мобильн\w+\s+кронштейн\w*|"
    r"подставк\w*|соединительн\w*|антивибрацион\w*|"
    r"гель|универсальн\w+\s+гель|порош\w*|universal\s+liquid|"
    r"сушилк\w*|сушильн\w+\s+машин\w*"
    r")",
    re.I,
)


def is_wanted(listing: Listing) -> bool:
    """False for the non-products asaxiy mixes into a category leaf.

    Applied in `sweep()` only -- `parse()` stays a faithful pure function of
    one document, as in every other client here.
    """
    return not _WRONG_PRODUCT.match(listing.name_raw or "")


def total_pages(page_html: str) -> int:
    """How many pages this category has, per the page's own script.

    Returns 1 when the marker is absent. That is the safe direction: a
    missing signal ends the sweep after one page (visible immediately as a
    coverage shortfall) rather than walking a paginator whose end we cannot
    see, against a site that answers out-of-range pages with page 1.
    """
    match = _TOTAL_PAGES.search(page_html or "")
    if match is None:
        logger.warning("asaxiy: no totalPages marker on this page; treating it as the last")
        return 1
    return max(1, int(match.group(1)))


def _card_listing(card: str) -> Listing | None:
    """One card -> a Listing, or None if the card is not a complete product.

    Every field comes from the cart data-attributes except the URL, which
    must independently name the same product id -- see the module docstring.
    """
    data = _CART_DATA.search(card)
    if data is None:
        return None
    product_id = data.group("id")
    attrs = {key: value for key, value in _ATTR.findall(data.group("attrs"))}

    link = _PRODUCT_LINK.search(card)
    if link is None or link.group("id") != product_id:
        # Either no product anchor in this chunk, or the chunk straddles a
        # card boundary and the anchor belongs to a different product. Both
        # are "we do not know this product's URL", and a price we cannot
        # attribute to a specific listing is worthless.
        logger.warning("asaxiy: no anchor matching product %s; dropping the card", product_id)
        return None

    # data-name-ru first: it is present even on an Uzbek page, so the parser
    # yields Russian names whichever language the request happened to get.
    name = attrs.get("name-ru") or attrs.get("name") or ""

    return try_build_listing(
        store_slug="asaxiy",
        source_key=product_id,
        # The attribute values are HTML-escaped in the document
        # ("bug&lsquo;", "&#039;"); unescaping is what makes them the same
        # strings the site renders, which is what the matcher expects.
        name_raw=html_module.unescape(name).strip(),
        price=coerce_price(attrs.get("price")),
        url=BASE_URL + link.group("path"),
        availability="IN_STOCK" if _ADD_TO_CART in card else "OUT_OF_STOCK",
        image_url=attrs.get("img") or None,
        raw={"id": product_id, **attrs},
    )


def parse(page_html: str) -> list[Listing]:
    """Turn one raw category page into Listings. Pure function, no I/O.

    Unfiltered and faithful to the document, like every other client's
    `parse()`. Category scoping is crawl policy and lives in the
    CATEGORY_PATHS leaves that `sweep()` requests.
    """
    listings = []
    for card in _CARD_BOUNDARY.split(page_html or "")[1:]:
        listing = _card_listing(card)
        if listing is not None:
            listings.append(listing)
    return listings


class AsaxiySource:
    slug = "asaxiy"
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
        url = CATEGORY_URL.format(path=path)
        return url if page <= 1 else f"{url}/page={page}"

    def sweep(self, category: str = "smartphones") -> Iterator[Listing]:
        """Every product in one asaxiy category, walking pagination to the end."""
        path = CATEGORY_PATHS.get(category)
        if path is None:
            raise ValueError(f"unknown category {category!r}")
        session = self._get_session()

        def fetch(page):
            return get_text(session, self._url(path, page))

        # The second stop. `totalPages` is the primary one, but an out-of-range
        # page here serves page 1 rather than nothing, so a wrong or missing
        # totalPages would walk to MAX_PAGES re-ingesting page 1 and record a
        # triumphant harvest of duplicates. Ids already seen cannot be new
        # products, so a page contributing none is the end of the catalogue
        # however we got there.
        #
        # `state` is what makes the two stops one mechanism rather than two
        # half-mechanisms: `paginate` yields a whole page's listings to the
        # loop below before it calls `following`, so by the time `following`
        # runs, `state["new"]` is exactly how many products THIS page added.
        state = {"new": 0}

        def following(page_html, page):
            if state["new"] == 0:
                logger.info("asaxiy %s: page %d added no product not already "
                            "seen; treating it as the end of the catalogue",
                            category, page)
                return None
            state["new"] = 0
            return page + 1 if page < total_pages(page_html) else None

        seen: set[str] = set()
        refused = 0
        for listing in paginate(fetch, parse, following):
            if listing.source_key in seen:
                continue
            seen.add(listing.source_key)
            state["new"] += 1
            if not is_wanted(listing):
                refused += 1
                continue
            yield replace(listing, category=category) if listing.category != category else listing
        # Counted and logged rather than dropped in silence: this number moving
        # is how a change to asaxiy's title template becomes visible, and the
        # denylist's own failure mode is refusing more than it should.
        if refused:
            logger.info("asaxiy %s: refused %d listings that are not %s",
                        category, refused, category)

    def search(self, query: str) -> Iterator[Listing]:
        """asaxiy's search is `/product?key=<term>`, the same grid markup.

        Present so the source satisfies the protocol; the sweep is what the
        harvest uses, and Pass B only queries sources that cannot be swept.
        """
        session = self._get_session()
        page_html = get_text(session, f"{BASE_URL}/ru/product", params={"key": query})
        yield from parse(page_html)
