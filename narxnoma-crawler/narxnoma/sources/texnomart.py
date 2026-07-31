"""texnomart.uz client: generic-query sweep, not a browsable catalogue.

texnomart's search endpoint accepts a broad query (`q=smartfon`) and returns
a paginated result set spanning the whole phone assortment, so `sweep()`
walks that pagination instead of hitting a per-category catalogue endpoint
(see docs/parsers/texnomart.md). `search()` reuses the same endpoint with
the caller's query text.
"""
from typing import Iterator

from narxnoma.sources.base import Listing, coerce_price, try_build_listing
from narxnoma.sources.http import get_json, polite_session

API_URL = "https://gw.texnomart.uz/api/common/v1/search/result"
PRODUCT_URL = "https://texnomart.uz/product/detail/{id}/"
SWEEP_QUERY = "smartfon"
LIMIT = 20

_HEADERS = {
    "accept-device": "web",
    "Accept-Language": "uz",
    "accept-region": "2",
}


def _parse_item(item: dict) -> Listing | None:
    product_id = item.get("id")
    name = item.get("name")
    # old_price is frequently 0 and must never be used as a price fallback --
    # sale_price is the only field texnomart guarantees to be current.
    price = coerce_price(item.get("sale_price"))

    return try_build_listing(
        store_slug="texnomart",
        source_key=str(product_id) if product_id else None,
        name_raw=name,
        price=price,
        url=PRODUCT_URL.format(id=product_id) if product_id else None,
        image_url=item.get("image"),
        raw=item,
    )


def parse(payload: dict) -> list[Listing]:
    """Turn one raw search-result response into Listings. Pure function, no I/O."""
    products = ((payload or {}).get("data") or {}).get("products") or []
    listings = []
    for item in products:
        lst = _parse_item(item)
        if lst is not None:
            listings.append(lst)
    return listings


class TexnomartSource:
    slug = "texnomart"
    can_sweep = True

    def __init__(self) -> None:
        self._session = None

    def _get_session(self):
        if self._session is None:
            self._session = polite_session(
                referer="https://texnomart.uz/",
                origin="https://texnomart.uz",
                extra_headers=_HEADERS,
            )
        return self._session

    def _paginate(self, query: str) -> Iterator[Listing]:
        session = self._get_session()
        page = 1
        last_page = 1
        while page <= last_page:
            # TODO(plan-3): no per-page error handling -- a transient failure
            # on any one page loses the rest of the sweep. Same gap as
            # olcha; deferred until partial-progress recovery is built once.
            payload = get_json(
                session,
                API_URL,
                params={"q": query, "page": page, "limit": LIMIT},
            )
            for listing in parse(payload):
                yield listing
            pagination = ((payload or {}).get("data") or {}).get("pagination") or {}
            last_page = pagination.get("total_page", last_page)
            page += 1

    def sweep(self) -> Iterator[Listing]:
        """Every phone texnomart returns for the generic query 'smartfon'."""
        yield from self._paginate(SWEEP_QUERY)

    def search(self, query: str) -> Iterator[Listing]:
        yield from self._paginate(query)
