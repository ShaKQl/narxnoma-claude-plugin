"""idea.uz client: brand-query sweep, no browsable catalogue and no pagination.

idea has no full-catalogue browse endpoint, so `sweep()` loops over a fixed
list of brand queries and calls the search endpoint once per brand with
`quantity=100` (the API honours this, ~74-94 items per call depending on the
brand -- see docs/parsers/idea.md); results are merged and deduplicated by
`source_key` since the same product can surface under more than one brand
query. `search(query)` issues the same call with the caller's query text.
"""
from typing import Iterator

from narxnoma.sources.base import Listing, coerce_price, try_build_listing
from narxnoma.sources.http import get_json, polite_session

API_URL = "https://api.idea.uz/api/v2/search"
QUANTITY = 100

# idea has no full-catalogue browse endpoint, so sweep() is a fixed list of
# brand queries merged together (see module docstring).
BRAND_QUERIES = [
    "Samsung", "Xiaomi", "Redmi", "Honor", "Apple",
    "Infinix", "Tecno", "realme", "Nokia",
]

_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "uz",
}


def _parse_item(item: dict) -> Listing | None:
    product_id = item.get("id")
    if not product_id:
        return None
    name = item.get("name")
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
    """Turn one raw search response into Listings. Pure function, no I/O."""
    products = (payload or {}).get("products") or []
    listings = []
    for item in products:
        lst = _parse_item(item)
        if lst is not None:
            listings.append(lst)
    return listings


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
        """
        seen: set[str] = set()
        for query in BRAND_QUERIES:
            for listing in self._fetch(query):
                if listing.source_key in seen:
                    continue
                seen.add(listing.source_key)
                yield listing

    def search(self, query: str) -> Iterator[Listing]:
        yield from self._fetch(query)
