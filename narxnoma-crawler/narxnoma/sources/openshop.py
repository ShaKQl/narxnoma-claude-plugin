"""openshop.uz client: single-seller shop, full-catalogue sweep in ~120 requests.

openshop.uz is a Next.js front end over a Laravel JSON API at
`https://web.openshop.uz/api/v1`. Every call is a **POST**, filters travel in
the **query string** (not the body), and `language: ru` / `Accept-Language: ru`
select Russian names. See docs/parsers/openshop.md for the full write-up.

Three endpoints matter:

- `POST /shop/product/get_products?category_id=..&page=..&per_page=48` -- the
  catalogue browse the shop's own category pages call. `per_page` is capped at
  **48** server-side (asking for 100 or 500 silently returns 48), and deep
  paging is capped too: an unfiltered walk stops yielding new products after
  ~2,400 (page 50), while `meta.total` says 5,731. Walking each of the 11
  top-level categories separately (largest: 1,577) stays under the cap and
  returns every product -- verified 2026-10-14, 5,723 unique ids.
- `POST /shop/product/search_product?q=..` -- the header search box. Fuzzy over
  the SEO `tags` field and capped at 60 results, so a precise query still
  returns the whole brand. Useful for a human, useless for identity.
- `POST /shop/product/get_product?slug=..` with body `{"with_variants": true}`
  -- one product plus its variant group (`variants.axes` = RAM / colour /
  storage chips, `variants.matrix` = every sibling product id with its own
  price). This is how openshop TAGS goods: each colour x memory combination is
  its own product with its own id, slug and price, tied together by `group.id`.

Price: `price.total` is what the customer pays now (after any discount);
`price.old_price` is the struck-through figure. Both are integer SUM -- no
tiyin trap here. The public product page's `<title>` repeats `price.total`
("... | Цена: 6 466 000 сум"), which gives verification an independent read.

Product URL: `https://openshop.uz/shop/product/<slug>?lang=ru`. The `link` field in
the payload points at `web.openshop.uz`, which is the API host, not the shop.
"""
import logging
import re
import time
from typing import Iterator

import requests

from narxnoma.sources.base import Listing, coerce_price, paginate, try_build_listing
from narxnoma.sources.http import get_text, polite_session, post_json

logger = logging.getLogger(__name__)

API = "https://web.openshop.uz/api/v1"
PRODUCTS_URL = f"{API}/shop/product/get_products"
PRODUCT_URL_API = f"{API}/shop/product/get_product"
TREE_URL = f"{API}/shop/category/categories_tree"
# `?lang=ru` matters: without it the page renders in Uzbek ("Narx: ... so'm").
PRODUCT_URL = "https://openshop.uz/shop/product/{slug}?lang=ru"

PER_PAGE = 48          # server-side cap; larger values are silently clamped
DEEP_PAGE_CAP = 2400   # an unfiltered walk stops yielding new ids past this
# The API advertises `x-ratelimit-limit: 120` per minute. narxnoma's default
# pause (0.3-0.6 s) can average under 0.5 s on a fast connection, so this
# client enforces its own floor rather than relying on NARXNOMA_MIN_DELAY.
MIN_INTERVAL = 0.55

_HEADERS = {
    "Accept-Language": "ru",
    # openshop reads the locale from a custom `language` header, not only from
    # Accept-Language -- without it, names come back in Uzbek.
    "language": "ru",
}

# narxnoma category -> openshop SUBcategory ids (second tree level), verified
# against categories_tree on 2026-10-14.
CATEGORY_SUBCATEGORY_IDS = {
    "smartphones": {4},
    "televisions": {8},     # "Для дома" -- TVs are subsubcategory 30 inside it
    "laptops": {154},       # 1225 laptops, 1226 gaming laptops, 1522 MacBook
    "acs": {163},
    "fridges": {163},
    "washers": {163},
    "ovens": {163},
}
# The subsubcategory (third level = product TYPE) that actually holds each
# category inside the parents above. A category absent here keeps its whole
# subcategory. `ovens` is stoves, built-in ovens and hobs -- not microwaves,
# which no other source files under `ovens`.
CATEGORY_SUBSUBCATEGORY_IDS = {
    "televisions": {30},
    "acs": {31},
    "fridges": {33, 34},
    "washers": {44, 1411},
    "ovens": {32, 1215, 1403},
}
# openshop files countertop mini-ovens under "Духовые шкафы" (1215): 19 of the
# 78 `ovens` listings on 2026-10-22 ("Мини-печь", "Мини печь", "Mini oven").
# No other source files them under `ovens` (see asaxiy.py), so nothing could
# ever price-compare against them. Dropped by title, the only signal there is.
CATEGORY_EXCLUDE = {
    "ovens": re.compile(r"^\s*(?:мини[\s-]*печ|mini\s*oven)", re.I),
}

# Russian page: "... | Цена: 6 466 000 сум"; Uzbek page: "... | Narx: 6 466 000 so'm".
_TITLE_PRICE = re.compile(r"(?:Цена|Narx):\s*([\d\s ]+)\s*(?:сум|so)")


def page_url(slug: str) -> str:
    return PRODUCT_URL.format(slug=slug)


def title_price(title: str) -> int | None:
    """The price a product page's <title> states, or None."""
    m = _TITLE_PRICE.search(title or "")
    return int(re.sub(r"\D", "", m.group(1))) if m else None


def _parse_item(item: dict, category: str = "smartphones") -> Listing | None:
    slug = item.get("slug")
    # One price field, one code path: `total` is the discounted figure the
    # customer pays; `old_price` is display-only.
    price = coerce_price((item.get("price") or {}).get("total"))
    return try_build_listing(
        store_slug="openshop",
        source_key=str(item.get("id") or ""),
        name_raw=item.get("name") or "",
        price=price,
        # Never item["link"]: that is the API host (web.openshop.uz), not the shop.
        url=page_url(slug) if slug else "",
        availability="IN_STOCK" if item.get("is_stock") else "OUT_OF_STOCK",
        image_url=item.get("thumbnail_img"),
        category=category,
        raw=item,
    )


def parse(payload: dict, category: str = "smartphones") -> list[Listing]:
    """Turn one get_products response into Listings. Pure function, no I/O.

    Unfiltered: category narrowing is crawl policy and lives in sweep().
    """
    listings = []
    for item in (payload or {}).get("data") or []:
        listing = _parse_item(item, category)
        if listing is not None:
            listings.append(listing)
    return listings


def next_page(payload: dict, page: int) -> int | None:
    """The pager decides; an empty or fully-filtered page never ends a sweep."""
    meta = (payload or {}).get("meta") or {}
    last = meta.get("last_page") or page
    return page + 1 if page < last else None


class OpenshopSource:
    slug = "openshop"
    can_sweep = True

    def __init__(self) -> None:
        self._session = None
        self._last_request = 0.0

    def _throttle(self) -> None:
        wait = MIN_INTERVAL - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = polite_session(
                referer="https://openshop.uz/",
                origin="https://openshop.uz",
                extra_headers=_HEADERS,
            )
        return self._session

    # -- raw access (no price fence) ------------------------------------------

    def category_tree(self) -> list[dict]:
        self._throttle()
        return post_json(self._get_session(), TREE_URL, json={}).get("data") or []

    def _page(self, page: int, **filters) -> dict:
        params = {"page": page, "per_page": PER_PAGE, "sort_by": "latest", **filters}
        self._throttle()
        return post_json(self._get_session(), PRODUCTS_URL, params=params)

    def iter_raw(self, **filters) -> Iterator[dict]:
        """Every raw product dict matching `filters` (category_id, search, ...).

        Raw on purpose: Listing's price fence (>= 100,000 SUM) would drop the
        cheap goods -- cables, kitchen tools, mugs -- that a whole-assortment
        comparison needs to see.
        """
        def fetch(page):
            return self._page(page, **filters)

        def raw_items(payload):
            return (payload or {}).get("data") or []

        def following(payload, page):
            total = ((payload or {}).get("meta") or {}).get("total") or 0
            if total > DEEP_PAGE_CAP and page == 1:
                # Not fatal -- the caller still gets the first ~2,400 -- but a
                # silently truncated sweep is exactly what must never pass as
                # complete, so say so.
                logger.warning("openshop: %s matches %s products, above the ~%s deep-paging cap; "
                               "split the query by category", filters, total, DEEP_PAGE_CAP)
            return next_page(payload, page)

        yield from paginate(fetch, raw_items, following, first_page=1)

    def iter_catalogue(self) -> Iterator[dict]:
        """The whole catalogue, walked one top-level category at a time."""
        seen: set[int] = set()
        for top in self.category_tree():
            got = 0
            for item in self.iter_raw(category_id=top["id"]):
                if item.get("id") in seen:
                    continue
                seen.add(item["id"])
                got += 1
                yield item
            logger.info("openshop: category %s %r -> %d products (declared %s)",
                        top["id"], top.get("name"), got, top.get("products_count"))

    def product_detail(self, slug: str) -> dict:
        """get_product: {product, variants, navbar, seo}."""
        self._throttle()
        return post_json(self._get_session(), PRODUCT_URL_API,
                         params={"slug": slug}, json={"with_variants": True}).get("data") or {}

    def page_title(self, slug: str) -> tuple[str, int | None]:
        """The public product page's <title> and the price it states.

        The page is server-rendered, so this is a read of what a customer sees,
        independent of the JSON listing the price was first taken from.
        """
        self._throttle()
        html = get_text(self._get_session(), page_url(slug), headers={"Accept": "text/html"})
        m = re.search(r"<title>(.*?)</title>", html, re.S)
        title = m.group(1).strip() if m else ""
        return title, title_price(title)

    # -- Source protocol -----------------------------------------------------

    def sweep(self, category: str = "smartphones") -> Iterator[Listing]:
        subs = CATEGORY_SUBCATEGORY_IDS.get(category)
        if subs is None:
            raise ValueError(f"unknown category {category!r}")
        keep = CATEGORY_SUBSUBCATEGORY_IDS.get(category)
        exclude = CATEGORY_EXCLUDE.get(category)
        for sub in sorted(subs):
            for item in self.iter_raw(subcategory_id=sub):
                if keep and item.get("subsubcategory_id") not in keep:
                    continue
                if exclude and exclude.search(item.get("name") or ""):
                    continue
                listing = _parse_item(item, category)
                if listing is not None:
                    yield listing

    def search(self, query: str) -> Iterator[Listing]:
        """get_products?search= -- paginated but fuzzy (the full name of one
        phone matches ~500 products). Raw listings; pick the variant by name."""
        for item in self.iter_raw(search=query):
            listing = _parse_item(item)
            if listing is not None:
                yield listing
