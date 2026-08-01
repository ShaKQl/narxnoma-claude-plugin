"""alifshop.uz client: multi-seller marketplace, brand-query sweep.

alifshop has no browsable catalogue -- like idea.uz, `sweep()` loops over a
fixed list of brand queries (see narxnoma.sources.brand_queries) and calls
the search endpoint once per brand per page. `page` is **0-based** here,
unlike beemarket/texnomart which are 1-based, and `size` is capped at 20
server-side regardless of what is requested. The smartphone category alone
runs to thousands of listings, too many to page through fully, so
`sweep()` stops at `n_pages` (from the response) or a practical cap of 3
pages (60 listings) per brand -- see docs/parsers/alifshop.md. `search(query)`
issues the same call with the caller's query text, page 0.

alifshop is a multi-seller marketplace: the same phone is listed by many
partners at different prices, and every one of those is a distinct,
legitimate offer -- `source_key` is the item's own `id` (a UUID assigned
per listing by alifshop itself), which distinguishes each partner's offer
even when the product name, brand, and even list price are identical. It
does not collapse multiple sellers of the same phone into one row, which
is exactly what this source must not do.

alifshop's price is in **tiyin** (1/100 SUM) -- see coerce_tiyin_price.

No per-item category signal exists. Unlike idea's `category_id` or
beemarket's `category.slug`, individual items in this response carry no
category field at all -- the only category information in the payload is
`aggregations.category`, a dataset-wide histogram over the *whole* result
set for the query (e.g. "Смартфоны Samsung": 690, "Микроволновые печи":
50). That histogram cannot label any single item, but the search endpoint
itself accepts that histogram's own bucket names back as a `category`
filter, and it genuinely narrows server-side (verified live: a "Samsung"
query returns 1,034 items; adding `"category": "Смартфоны Samsung"` drops
that to 690, all genuine phones; adding a nonsense category value returns
0, proving the server really filters rather than ignoring an unknown key).
The catch is the bucket name is brand-specific ("Смартфоны Samsung",
"Смартфоны Xiaomi", ...), so it must be discovered per brand query rather
than hardcoded -- see `phone_category_from_aggregations`. `sweep()` fetches
page 0 unfiltered once per brand to read the aggregation, then re-requests
with the discovered `category` value and paginates that filtered set. If
no phone-like bucket is found (a retailer rename), it logs a warning and
falls back to the old unfiltered sweep for that brand rather than yielding
nothing.
"""
import logging
from typing import Iterator

from narxnoma.sources.base import Listing, coerce_price, try_build_listing
from narxnoma.sources.brand_queries import BRAND_QUERIES
from narxnoma.sources.http import polite_session, post_json

logger = logging.getLogger(__name__)

API_URL = "https://gw.alifshop.uz/web/client/search/full-text"
# Not .../product/<slug> -- that 404s ("Biz buni topa olmadik"). The slug
# from the API is correct; only this path prefix differs. Verified live by
# opening a generated link in a browser -- see docs/parsers/alifshop.md.
PRODUCT_URL = "https://alifshop.uz/moderated-offer/{slug}"

SIZE = 20  # server-side cap; asking for more is silently ignored
MAX_PAGES = 3  # practical cap per brand query -- 60 listings is enough for a stable median

_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "ru",
    "Content-Type": "application/json",
    # Fixed public string, not a credential.
    "service-token": "service-token-alifshop",
}


def _coerce_tiyin_price(raw_price) -> int | None:
    """Convert alifshop's tiyin price to SUM.

    The single most dangerous unit bug in this project: alifshop reports
    price in tiyin (1/100 SUM). There is exactly one price field and one
    code path here on purpose -- a *partial* divisor bug (dividing on one
    path but not another) produces prices 100x too large that still look
    plausible and would slip past PRICE_MIN/PRICE_MAX undetected. Always
    run the raw value through coerce_price first so non-numeric/None/zero
    values are rejected the same way every other source rejects them,
    *then* divide -- never divide an already-untrusted raw value.
    """
    tiyin = coerce_price(raw_price)
    if tiyin is None:
        return None
    return tiyin // 100


def _parse_item(item: dict) -> Listing | None:
    item_id = item.get("id")
    if not item_id:
        return None
    slug = item.get("slug")
    if not slug:
        return None
    product = item.get("product") or {}
    name = product.get("name")
    price = _coerce_tiyin_price(item.get("price"))

    quantity = item.get("quantity") or 0
    availability = "IN_STOCK" if quantity > 0 else "OUT_OF_STOCK"

    title_image = product.get("title_image") or {}

    return try_build_listing(
        store_slug="alifshop",
        source_key=str(item_id),
        name_raw=name,
        price=price,
        url=PRODUCT_URL.format(slug=slug),
        availability=availability,
        image_url=title_image.get("sm_path"),
        raw=item,
    )


def parse(payload: dict) -> list[Listing]:
    """Turn one raw search response into Listings. Pure function, no I/O.

    Unfiltered and faithful to the payload -- category narrowing happens at
    the request, via `category` in the search body (see module docstring
    and `phone_category_from_aggregations`), not here. parse() must stay a
    pure, unfiltered view of whatever payload it is given, filtered or not.
    """
    items = (payload or {}).get("items") or []
    listings = []
    for item in items:
        lst = _parse_item(item)
        if lst is not None:
            listings.append(lst)
    return listings


def phone_category_from_aggregations(payload: dict) -> str | None:
    """Pick the phones bucket out of a response's category facet.

    alifshop has no per-item category, but the search backend facets on
    category and accepts that facet's own display string as a filter. The
    bucket names are brand-specific ("Смартфоны Samsung"), so the value has
    to be discovered per query rather than hardcoded.

    Matching rule: `key.casefold().startswith("смартфон")` -- a *prefix*
    test, not a substring test. The observed bucket "Чехлы для смартфонов"
    (phone cases) *contains* "смартфон" and a naive `in` check would select
    it -- precisely the noise this filtering exists to remove. "Смарт-часы"
    (smartwatches) starts with "смарт" but not "смартфон", so the prefix
    rule correctly excludes it too.

    Reads defensively: a missing `aggregations` key, an empty `terms` list,
    or non-dict/non-string junk in a bucket all just yield no match. If
    more than one bucket matches (unexpected, but not impossible), the one
    with the largest doc_count wins and the rest are logged.
    """
    terms = (((payload or {}).get("aggregations") or {}).get("category") or {}).get("terms") or []
    matches = [
        term for term in terms
        if isinstance(term, dict)
        and isinstance(term.get("key"), str)
        and term["key"].casefold().startswith("смартфон")
    ]
    if not matches:
        return None
    best = max(matches, key=lambda term: term.get("doc_count") or 0)
    others = [term for term in matches if term is not best]
    if others:
        logger.info(
            "alifshop: multiple phone-like category buckets, picked %r (doc_count=%s); others=%s",
            best["key"],
            best.get("doc_count"),
            [(term["key"], term.get("doc_count")) for term in others],
        )
    return best["key"]


class AlifshopSource:
    slug = "alifshop"
    can_sweep = True

    def __init__(self) -> None:
        self._session = None

    def _get_session(self):
        if self._session is None:
            self._session = polite_session(
                referer="https://alifshop.uz/",
                origin="https://alifshop.uz",
                extra_headers=_HEADERS,
            )
        return self._session

    def _fetch(self, query: str, page: int, category: str | None = None) -> dict:
        session = self._get_session()
        body = {"query": query, "page": page, "size": SIZE}
        if category:
            body["category"] = category
        return post_json(session, API_URL, json=body)

    def sweep(self) -> Iterator[Listing]:
        """Every phone alifshop returns across a fixed list of brand
        queries, walking pagination up to n_pages or MAX_PAGES per brand
        (see module docstring). Deduplicated by source_key across brand
        queries -- not across sellers -- since the same listing can
        surface under more than one brand query (e.g. a "Redmi" phone
        matching both the "xiaomi" and "redmi" queries), but distinct
        seller offers of the same phone must each survive as their own
        listing.

        Per brand: fetch page 0 unfiltered (one request, doubles as both
        the first page of items and the aggregation used to find the
        phones bucket -- see phone_category_from_aggregations), then
        re-request page 0 *with* the discovered `category` and paginate
        that filtered result set. That costs one extra request per brand
        and removes roughly two-thirds of the sweep's non-phone noise
        (measured: "Samsung" 1,034 -> 690 items, 52 -> 35 pages). If no
        phone-like bucket is found, log a warning naming the brand and
        fall back to the unfiltered sweep, so a retailer renaming its
        buckets degrades to the old behaviour rather than to an empty
        catalogue.
        """
        seen: set[str] = set()
        for query in BRAND_QUERIES:
            first_payload = self._fetch(query, 0)
            category = phone_category_from_aggregations(first_payload)
            if category:
                logger.info(
                    "alifshop: narrowing brand query %r to category %r", query, category
                )
                payload = self._fetch(query, 0, category=category)
            else:
                logger.warning(
                    "alifshop: no phone category bucket found for brand query %r; "
                    "falling back to unfiltered sweep",
                    query,
                )
                payload = first_payload

            page = 0
            n_pages = 1
            while page < n_pages and page < MAX_PAGES:
                # TODO(plan-3): no per-page error handling -- a transient
                # failure on any one page loses the rest of this brand's
                # sweep. Same gap as olcha/texnomart/idea/beemarket;
                # deferred until partial-progress recovery is built once.
                for listing in parse(payload):
                    if listing.source_key in seen:
                        continue
                    seen.add(listing.source_key)
                    yield listing
                n_pages = (payload or {}).get("n_pages") or n_pages
                page += 1
                if page < n_pages and page < MAX_PAGES:
                    payload = self._fetch(query, page, category=category)

    def search(self, query: str) -> Iterator[Listing]:
        payload = self._fetch(query, 0)
        yield from parse(payload)
