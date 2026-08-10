"""market.beeline.uz (BeeMarket) client: category-scoped sweep, generic search.

BeeMarket is fully browsable, but the task brief's documented endpoint
(`GET /api/web/search?q=&is_bshop=1`) is a sweep of BeeMarket's *entire*
electronics catalogue -- phones, headphones, air fryers, keyboards, network
gear -- 4,306 items across 270 pages as of 2026-07-31, to find a few hundred
phones. A live probe found a cheaper, genuinely server-side-narrowed
alternative: `GET /api/web/categories/smartfony/products`, the same request
BeeMarket's own https://market.beeline.uz/smartfony category page issues.
It returned 436 items across 28 pages, every one of them category
`smartfony` with `is_smartphone: true` -- so `sweep()` uses it instead of
the generic search.

Probes tried and their results (see docs/parsers/beemarket.md for the
retailer's documented shape):
  - `category=smartfony` / `category_id=1` / `category_ids[]=1` /
    `category_slug=smartfony` / `is_smartphone=1` as extra params on the
    generic `/api/web/search` endpoint: all silently ignored -- total and
    last_page stayed at 4,306 / 270 regardless.
  - `q=smartfon` (the texnomart-style broad category-name query) on
    `/api/web/search`: BeeMarket's search does literal AND text matching
    against product names, which don't contain the word "smartfon" --
    returned 1 irrelevant accessory, not the phone catalogue.
  - `/api/web/categories/smartfony/products`: genuinely narrows server-side
    (436 items / 28 pages vs 4,306 / 270). Found by watching the network
    requests BeeMarket's own frontend makes when browsing to
    https://market.beeline.uz/smartfony. `q=` and `is_bshop=` have no
    observed effect on this endpoint (page contents were identical with and
    without them), so it always returns BeeMarket's full smartfony catalogue
    regardless of those params -- sweep() still passes `is_bshop=1` per the
    brief's documented contract in case that changes.

`search(query)` has no equivalent category-scoped shortcut (the category
endpoint ignores `q`), so it uses the documented generic search endpoint,
which does honour `q` (confirmed live: `q=Honor X6c` returned 74 items, all
Honor-branded, vs 4,306 unfiltered).

`parse()` is unfiltered and works unchanged against either endpoint's
response -- both return the same doubly-nested `data.data` list / envelope
shape. Category filtering is crawl policy, not parsing, so it lives in
`sweep()`'s `_filter_phone_listings` instead (see PHONE_CATEGORY_SLUGS).
"""
import logging
from collections import Counter
from dataclasses import replace
from typing import Iterator

from narxnoma.sources.base import Listing, coerce_price, paginate, try_build_listing
from narxnoma.sources.http import get_json, polite_session

logger = logging.getLogger(__name__)

# The documented generic search endpoint (task brief / docs/parsers/beemarket.md).
# Used by search(), which needs `q` to actually filter -- see module docstring.
API_URL = "https://market.beeline.uz/api/web/search"

# The category-scoped endpoint sweep() uses instead of API_URL -- see module
# docstring for why. This is the same request BeeMarket's own category page
# issues; it is undocumented by the retailer (not in docs/parsers/beemarket.md)
# but was confirmed live on 2026-07-31 to return only the smartfony category.
SWEEP_CATEGORY_SLUG = "smartfony"
SWEEP_API_URL = "https://market.beeline.uz/api/web/categories/{slug}/products"

PRODUCT_URL = "https://market.beeline.uz/{category_slug}/{slug}"
DEFAULT_CATEGORY_SLUG = "smartfony"

# Plan 5: category -> beemarket category.slug, verified live 2026-08-10 from
# /api/web/categories/list (smartfony id=1 top-level; the rest are leaves under
# Elektronika / Крупная бытовая техника).
CATEGORY_SLUGS = {
    "smartphones": "smartfony",
    "televisions": "televisions",           # id 68
    "laptops": "laptops",                   # id 113
    "acs": "air-conditioners",              # id 86
    "fridges": "refrigerators",             # id 52
    "washers": "washing-machines",          # id 50
    "ovens": "built-in-ovens",              # id 136
}

# category.slug is BeeMarket's only human-readable category signal (unlike
# idea's undocumented numeric category_id). Observed live on 2026-07-31 by
# sweeping the generic, unscoped /api/web/search?q=&is_bshop=1 page 1 and
# inspecting every item's category.slug:
#   smartfony            = smartphones (e.g. Honor X9d, Huawei Nova Y63)
#   headphones            = headphones / charging cables
#   aerogrills-fryers      = air fryers
#   keyboards              = keyboards
#   network-equipment      = Wi-Fi access points
# and confirmed against /api/web/categories/list: "smartfony" (id 1) is a
# top-level category with no active_children, i.e. the sole phone category
# -- there is no separate feature-phone or tablet category to also include.
# Only smartfony is a phone category. The phone slug list still drives the
# smartphones filter; non-phone sweeps trust the category-scoped endpoint.
PHONE_CATEGORY_SLUGS = frozenset({"smartfony"})

_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "ru",
}


def _parse_item(item: dict) -> Listing | None:
    item_id = item.get("id")
    if not item_id:
        return None
    slug = item.get("slug")
    if not slug:
        return None
    name = item.get("name")

    # Fallback chain verified against the live API and used in practice by
    # the seed implementation: actual_price (current, discount applied) ->
    # discount_price -> price (struck-through pre-discount list price, do
    # not use unless nothing else is available).
    price = coerce_price(item.get("actual_price"))
    if price is None:
        price = coerce_price(item.get("discount_price"))
    if price is None:
        price = coerce_price(item.get("price"))

    category_slug = ((item.get("category") or {}).get("slug")) or DEFAULT_CATEGORY_SLUG
    url = PRODUCT_URL.format(category_slug=category_slug, slug=slug)

    return try_build_listing(
        store_slug="beemarket",
        source_key=str(item_id),
        name_raw=name,
        price=price,
        url=url,
        image_url=item.get("image_url") or item.get("image"),
        raw=item,
    )


def parse(payload: dict) -> list[Listing]:
    """Turn one raw response into Listings. Pure function, no I/O.

    Unfiltered and faithful to the payload -- category filtering is crawl
    policy, not parsing, and belongs in sweep() instead (see
    _filter_phone_listings and PHONE_CATEGORY_SLUGS). Works identically
    whichever endpoint the payload came from: both API_URL and
    SWEEP_API_URL share the same doubly-nested `data.data` item list /
    `data.last_page` envelope.
    """
    items = ((payload or {}).get("data") or {}).get("data") or []
    listings = []
    for item in items:
        lst = _parse_item(item)
        if lst is not None:
            listings.append(lst)
    return listings


def _filter_phone_listings(listings: list[Listing]) -> list[Listing]:
    """Keep only listings in PHONE_CATEGORY_SLUGS; log the category mix seen.

    Category filtering is crawl policy (V1 is smartphones only), so it
    lives here rather than in parse(), which stays a pure, unfiltered view
    of the payload. Extracted as a standalone function so it is testable
    directly against a recorded fixture, without a live sweep. sweep() only
    calls the category-scoped SWEEP_API_URL, which should already return
    nothing but smartfony -- this filter is defense in depth for the day
    that stops being true (a retailer rename, a scoping regression, etc.).
    """
    def category_slug(listing: Listing) -> str | None:
        return (listing.raw.get("category") or {}).get("slug")

    counts = Counter(category_slug(listing) for listing in listings)
    logger.info("beemarket category distribution: %s", dict(counts))
    filtered_out = {slug: n for slug, n in counts.items() if slug not in PHONE_CATEGORY_SLUGS}
    if filtered_out:
        logger.info("beemarket filtered out non-phone categories: %s", filtered_out)
    return [listing for listing in listings if category_slug(listing) in PHONE_CATEGORY_SLUGS]


class BeemarketSource:
    slug = "beemarket"
    can_sweep = True

    def __init__(self) -> None:
        self._session = None

    def _get_session(self):
        if self._session is None:
            self._session = polite_session(
                referer="https://market.beeline.uz/",
                extra_headers=_HEADERS,
            )
        return self._session

    def sweep(self, category: str = "smartphones") -> Iterator[Listing]:
        """Every item in one category, walking pagination to the end.

        Phones hit the smartfony category endpoint and are additionally run
        through the phone filter (defense in depth). Non-phone categories
        trust their category-scoped endpoint (the slugs in CATEGORY_SLUGS are
        verified live leaves, so no phone filter applies). Every listing is
        tagged with the sweep's category.
        """
        slug = CATEGORY_SLUGS.get(category)
        if slug is None:
            raise ValueError(f"unknown category {category!r}")
        url = SWEEP_API_URL.format(slug=slug)
        post_filter = _filter_phone_listings if category == "smartphones" else None
        for listing in self._walk(url, {"is_bshop": 1}, post_filter):
            if listing.category != category:
                listing = replace(listing, category=category)
            yield listing

    def search(self, query: str) -> Iterator[Listing]:
        yield from self._walk(API_URL, {"q": query, "is_bshop": 1})

    def _walk(self, url, params, post_filter=None) -> Iterator[Listing]:
        session = self._get_session()

        def fetch(page):
            return get_json(session, url, params={**params, "page": page})

        def parse_page(payload):
            listings = parse(payload)
            return post_filter(listings) if post_filter else listings

        def following(payload, page):
            data = (payload or {}).get("data") or {}
            return page + 1 if page < data.get("last_page", page) else None

        yield from paginate(fetch, parse_page, following)
