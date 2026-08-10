"""mediapark.uz client: autocomplete-only, no sweep.

mediapark exposes exactly one endpoint: a Diginetica autocomplete search
(`GET .../v1/diginetica/autocomplete?st=<text>&lang=ru`). There is no
full-catalogue browse endpoint and no pagination -- a query returns only
the top ~5-10 ranked hits. That makes a sweep structurally impossible, not
merely unimplemented: `can_sweep = False` and `sweep()` **raises**
`NotImplementedError` rather than yielding an empty iterator. An empty
iterator would let a caller that forgot to check `can_sweep` record a
perfectly successful harvest of zero listings -- silently, and
indistinguishable from a source whose catalogue really is empty. Raising
is what tells a careless caller, loudly, that it skipped the guard. Task
11's harvest stage must check `can_sweep` and skip this source rather than
call `sweep()` and catch the error.

Driving mediapark per-variant across a harvest cycle needs a variant list
that does not exist yet (Plan 3) -- out of scope here. Only `search(query)`
is implemented; `search()` forwards the caller's query text verbatim as
`st`, unlike beemarket/texnomart's `search()` which also just forwards the
caller's text. What is different about mediapark is the *quality* of the
query the caller should send: because this is a ranking autocomplete
engine rather than a strict-AND filter, dropping the RAM/storage half of a
query (the aggressive stripping used to build texnomart/beemarket queries)
measurably worsens recall here -- the exact variant needs to rank into a
short list of ~10, so callers should keep the query close to verbatim,
including the "6/128" form and the colour word (see docs/parsers/mediapark.md
section 4). That query-shaping is the caller's responsibility (task 11 /
matching), not something this module does to the string it's given.

No per-item category signal exists. Each product in the recorded response
carries only id/name/price/imageUrl/imageUrls/linkUrl/available/score/
oldPrice -- no category id or slug. The top-level `categories` key is a
taxonomy of *search-suggestion* links (e.g. "Смартфоны", "Samsung Galaxy
A15 | A16 | A17") with no back-reference to any item in `products`, so it
cannot be used to filter individual listings; unlike idea's category_id or
beemarket's category.slug, it doesn't label any specific product. A live
"Samsung" query (the recorded fixture) returned 10 items, all phones --
no off-category noise was observed in this recording, but since there is
no reusable per-item signal either way, `parse()` stays unfiltered and no
category filter is implemented. Off-category noise also matters less here
than for the other clients: there is no sweep to pollute, only individual
search() calls a caller inspects one at a time.
"""
import logging
from typing import Iterator

from narxnoma.sources.base import Listing, coerce_price, try_build_listing
from narxnoma.sources.http import get_json, polite_session

logger = logging.getLogger(__name__)

API_URL = "https://api.v2.mediapark.uz/v1/diginetica/autocomplete"

# The linkUrl mediapark hands back is relative; this is the only prefix
# ever applied to it. The slug it contains can lie about specs (see
# docs/parsers/mediapark.md section 3) -- it must never be parsed or
# reconstructed, only prefixed verbatim.
LINK_PREFIX = "https://mediapark.uz"

# x-device-id / x-session-id must be *present* but are not credentials --
# any value works (confirmed in docs/parsers/mediapark.md). Fixed strings,
# not secrets.
_HEADERS = {
    "Accept": "*/*",
    "Content-Type": "application/json",
    "Accept-Language": "ru",
    "x-device-id": "Ywh1FNq17HzyCBJ15BDZl",
    "x-session-id": "vzNu2usamNvHs6plQvNO4",
}


def _parse_item(item: dict) -> Listing | None:
    item_id = item.get("id")
    if not item_id:
        return None
    link = item.get("linkUrl")
    if not link:
        return None
    name = item.get("name")
    # price arrives as a string ("2699000") -- coerce_price handles the cast.
    price = coerce_price(item.get("price"))

    return try_build_listing(
        store_slug="mediapark",
        source_key=str(item_id),
        name_raw=name,
        price=price,
        # linkUrl verbatim, only ever prefixed with the host -- see module
        # docstring and docs/parsers/mediapark.md section 3 for why it must
        # never be parsed or reconstructed.
        url=LINK_PREFIX + link,
        image_url=item.get("imageUrl"),
        raw=item,
    )


def parse(payload: dict) -> list[Listing]:
    """Turn one raw autocomplete response into Listings. Pure function, no I/O.

    Unfiltered and faithful to the payload -- see module docstring for why
    no category filter exists (no usable per-item signal). Only the
    `products` key is read; `suggestions` and `categories` are query-
    refinement data, not listings.
    """
    products = (payload or {}).get("products") or []
    listings = []
    for item in products:
        lst = _parse_item(item)
        if lst is not None:
            listings.append(lst)
    return listings


class MediaparkSource:
    slug = "mediapark"
    can_sweep = False

    def __init__(self) -> None:
        self._session = None

    def _get_session(self):
        if self._session is None:
            self._session = polite_session(
                referer="https://mediapark.uz/",
                origin="https://mediapark.uz",
                extra_headers=_HEADERS,
            )
        return self._session

    def sweep(self, category: str = "smartphones") -> Iterator[Listing]:
        """Always raises -- mediapark has no full-catalogue endpoint.

        Deliberately not an empty generator: see module docstring for why
        an empty iterator here would be a silent failure mode this project
        exists to prevent. Callers must check `can_sweep` before calling
        this; Task 11's harvest stage does exactly that.
        """
        raise NotImplementedError(
            "mediapark is search-only: it exposes only an autocomplete "
            "endpoint with no full-catalogue browse and no pagination, so "
            "there is no way to sweep it. Check can_sweep before calling "
            "sweep()."
        )

    def search(self, query: str) -> Iterator[Listing]:
        session = self._get_session()
        payload = get_json(session, API_URL, params={"st": query, "lang": "ru"})
        yield from parse(payload)
