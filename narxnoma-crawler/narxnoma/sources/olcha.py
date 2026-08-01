"""olcha.uz client: full-catalogue pull, not per-query search.

olcha's search endpoint caps results per query, so a full sweep of the
smartphone category is fewer calls and better coverage than one search per
phone (see docs/parsers/olcha.md). `search()` therefore filters the swept
catalogue client-side rather than hitting a different endpoint.
"""
from typing import Iterator

from narxnoma.sources.base import Listing, coerce_price, try_build_listing
from narxnoma.sources.http import get_json, polite_session

API_URL = "https://mobile.olcha.uz/api/v2/products"
PRODUCT_URL = "https://olcha.uz/ru/product/view/{alias}"
CATEGORY = "telefony"
PER_PAGE = 20  # server caps per_page at 20 regardless of what is requested

_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "ru",
    "clientmodel": "web",
}


def _parse_item(item: dict) -> Listing | None:
    alias = item.get("alias")
    name = item.get("name_ru")
    # discount_price arrives as int, total_price as string -- coerce_price
    # handles both so this fallback doesn't silently break on type alone.
    price = coerce_price(item.get("discount_price"))
    if price is None:
        price = coerce_price(item.get("total_price"))
    if not alias:
        return None

    quantity = item.get("quantity") or 0
    availability = "IN_STOCK" if quantity else "OUT_OF_STOCK"

    return try_build_listing(
        store_slug="olcha",
        source_key=alias,
        name_raw=name,
        price=price,
        url=PRODUCT_URL.format(alias=alias),
        availability=availability,
        image_url=item.get("main_image"),
        raw=item,
    )


def parse(payload: dict) -> list[Listing]:
    """Turn one raw catalogue-page response into Listings. Pure function, no I/O."""
    products = ((payload or {}).get("data") or {}).get("products") or []
    listings = []
    for item in products:
        lst = _parse_item(item)
        if lst is not None:
            listings.append(lst)
    return listings


class OlchaSource:
    slug = "olcha"
    can_sweep = True

    def __init__(self) -> None:
        self._session = None
        self._catalogue: list[Listing] | None = None

    def _get_session(self):
        if self._session is None:
            self._session = polite_session(
                referer="https://olcha.uz/",
                origin="https://olcha.uz",
                extra_headers=_HEADERS,
            )
        return self._session

    def sweep(self) -> Iterator[Listing]:
        """Every phone in olcha's telefony category, walking pagination to the end."""
        session = self._get_session()
        page = 1
        last_page = 1
        while page <= last_page:
            # TODO(plan-3): no per-page error handling -- a transient failure
            # on any one page (e.g. page 12 of 23) loses the whole sweep.
            # Partial-progress recovery (retry/resume) is deferred; the next
            # six clients inherit this same gap until it's built once, here.
            payload = get_json(
                session,
                API_URL,
                params={"page": page, "per_page": PER_PAGE, "category": CATEGORY},
            )
            for listing in parse(payload):
                yield listing
            paginator = ((payload or {}).get("data") or {}).get("paginator") or {}
            last_page = paginator.get("last_page", last_page)
            page += 1

    def search(self, query: str) -> Iterator[Listing]:
        """olcha has no search endpoint; filter the already-swept catalogue by name."""
        if self._catalogue is None:
            self._catalogue = list(self.sweep())
        needle = query.casefold()
        for listing in self._catalogue:
            if needle in listing.name_raw.casefold():
                yield listing
