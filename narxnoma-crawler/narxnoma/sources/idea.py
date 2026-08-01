"""idea.uz client: brand-query sweep, no browsable catalogue and no pagination.

idea has no full-catalogue browse endpoint, so `sweep()` loops over a fixed
list of brand queries and calls the search endpoint once per brand with
`quantity=100` (the API honours this, ~74-94 items per call depending on the
brand -- see docs/parsers/idea.md); results are merged and deduplicated by
`source_key` since the same product can surface under more than one brand
query. `search(query)` issues the same call with the caller's query text.

idea also mixes non-phone categories (appliances) into every response with
no reliable textual signal to tell them apart, so `sweep()` filters on the
undocumented `category_id` field before yielding -- see PHONE_CATEGORY_IDS
and docs/parsers/idea.md.
"""
import logging
from collections import Counter
from typing import Iterator

from narxnoma.sources.base import Listing, coerce_price, try_build_listing
from narxnoma.sources.brand_queries import BRAND_QUERIES
from narxnoma.sources.http import get_json, polite_session

logger = logging.getLogger(__name__)

API_URL = "https://api.idea.uz/api/v2/search"
QUANTITY = 100

# idea has no full-catalogue browse endpoint, so sweep() is a fixed list of
# brand queries merged together (see module docstring) -- this list *is*
# the sweep's entire reach into idea's catalogue. Any brand missing here is
# permanently invisible to us. alifshop.py needs the identical list for the
# same reason, so it is shared rather than duplicated -- see
# narxnoma.sources.brand_queries (imported above) for the derivation and
# rationale.

# idea's `category_id` is the only usable category signal -- the textual
# `category`/`category_name`/`category_slug` fields are null or empty on
# every observed item. It is completely undocumented by the retailer;
# these mappings were derived by observation from the recorded fixture
# (tests/fixtures/sources/idea.json) and a live "Samsung" sweep on
# 2026-07-31:
#   55 = smartphones (e.g. Galaxy S25 Ultra, Galaxy A36)
#   26 = vacuum cleaners
#   24 = fridges
#    9 = TVs
# Only 55 is a phone category; V1 is smartphones only. Because these ids
# are undocumented and could be renumbered or a second phone category
# added without notice, sweep() logs the full category distribution every
# run (see _filter_phone_listings) so drift is visible instead of silently
# emptying or polluting the catalogue.
PHONE_CATEGORY_IDS = frozenset({55})

_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "uz",
}


def _parse_item(item: dict) -> Listing | None:
    product_id = item.get("id")
    if not product_id:
        return None
    # `name` is BRANDLESS: idea stores it as the model half only
    # ('VCC 5252 Black', 'Galaxy S25 Ultra 12/256 Titanium Blue'), while
    # `title_name` carries the same text with the brand in front
    # ('Samsung VCC 5252 Black changyutgichi'). Brand is a hard identity
    # field downstream -- variant_key() returns None without it -- so a
    # brandless name_raw is not a slightly worse name, it is an offer that
    # can never be clustered and silently drops out of the catalogue.
    # Measured on the recorded fixture: with `name`, 0 of 20 listings were
    # keyable; with `title_name`, 6 of 20 (and 14 of 20 recover a brand).
    # `title_name` is occasionally absent or empty, hence the fallback --
    # a brandless name still beats no listing at all.
    name = (item.get("title_name") or "").strip() or item.get("name")
    price = coerce_price(item.get("current_price"))

    return try_build_listing(
        store_slug="idea",
        source_key=str(product_id),
        name_raw=name,
        price=price,
        # idea is the only source that hands back a complete, ready-to-use
        # product URL -- take it verbatim, never reconstruct one from slug.
        url=item.get("url"),
        image_url=item.get("img"),
        raw=item,
    )


def parse(payload: dict) -> list[Listing]:
    """Turn one raw search response into Listings. Pure function, no I/O.

    Unfiltered and faithful to the payload -- category filtering is crawl
    policy, not parsing, and belongs in sweep() instead (see
    _filter_phone_listings and PHONE_CATEGORY_IDS).
    """
    products = (payload or {}).get("products") or []
    listings = []
    for item in products:
        lst = _parse_item(item)
        if lst is not None:
            listings.append(lst)
    return listings


def _filter_phone_listings(listings: list[Listing]) -> list[Listing]:
    """Keep only listings in PHONE_CATEGORY_IDS; log the category mix seen.

    Category filtering is crawl policy (V1 is smartphones only), so it
    lives here rather than in parse(), which stays a pure, unfiltered view
    of the payload. Extracted as a standalone function so it is testable
    directly against a recorded fixture, without a live sweep.
    """
    counts = Counter(listing.raw.get("category_id") for listing in listings)
    logger.info("idea category distribution: %s", dict(counts))
    filtered_out = {cid: n for cid, n in counts.items() if cid not in PHONE_CATEGORY_IDS}
    if filtered_out:
        logger.info("idea filtered out non-phone categories: %s", filtered_out)
    return [
        listing for listing in listings
        if listing.raw.get("category_id") in PHONE_CATEGORY_IDS
    ]


class IdeaSource:
    slug = "idea"
    can_sweep = True

    def __init__(self) -> None:
        self._session = None

    def _get_session(self):
        if self._session is None:
            self._session = polite_session(
                referer="https://idea.uz/",
                origin="https://idea.uz",
                extra_headers=_HEADERS,
            )
        return self._session

    def _fetch(self, query: str) -> list[Listing]:
        session = self._get_session()
        payload = get_json(
            session,
            API_URL,
            # type[] is a repeated query parameter, not a comma list --
            # requests expands a list value into repeated type[]= pairs.
            params={"search": query, "quantity": QUANTITY, "type[]": ["shops", "products"]},
        )
        return parse(payload)

    def sweep(self) -> Iterator[Listing]:
        """Every phone idea returns across a fixed list of brand queries.

        There is no pagination and no full-catalogue endpoint, so this
        merges one search call per brand and deduplicates by source_key --
        the same product can appear under more than one brand query.
        Non-phone categories (appliances) are filtered out here; see
        PHONE_CATEGORY_IDS and _filter_phone_listings.
        """
        seen: set[str] = set()
        for query in BRAND_QUERIES:
            for listing in _filter_phone_listings(self._fetch(query)):
                if listing.source_key in seen:
                    continue
                seen.add(listing.source_key)
                yield listing

    def search(self, query: str) -> Iterator[Listing]:
        yield from self._fetch(query)
