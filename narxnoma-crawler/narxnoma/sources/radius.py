"""radius.uz client: a Saleor storefront, queried through its public GraphQL.

The cleanest source of the nine. radius.uz runs Saleor, and its own front end
talks to `https://new.api.radius.uz/graphql/` anonymously -- no token, no
signing, no per-brand search. One query per category walks the whole thing
with cursor pagination, and every field we need is a typed column rather than
a string to be parsed: `name`, `brand.name`, `pricing.priceRange.start.amount`
(plain UZS), `isAvailable`, `variants[].sku`.

It is also the SMALLEST source: ~180 products across our seven categories,
against asaxiy's 693 and uzum's 5,461. That is not a defect and not a reason
to skip it. radius is a real Tashkent retailer with its own pricing, and a
source's value to a price comparison is the number of products it puts a
SECOND price on, not the number of rows it adds. Measured after the first
harvest, and recorded in docs/parsers/radius.md.

TWO TRAPS, both measured live 2026-08-11:

1. **The product URL is built from the DEFAULT VARIANT id, not the product
   id.** The site links to `/ru/product/<N>-<product-slug>`, and `N` is
   `defaultVariant.id`. Building it from `Product.id` yields a clean 404 on
   every product -- checked on six, all 404. This is exactly the trap
   docs/parsers/README.md rule 1 exists for ("never trust a slug you built
   yourself"), and it is invisible from the payload alone: both ids are
   plausible integers sitting next to the slug.

2. **Not every category hangs where its name suggests.** `noutbuki` holds 9
   laptops and none of them are Apple: the 7 MacBooks live under a top-level
   "Apple" category, as do the iPhones, which are absent from `smartfony`.
   Sweeping the obvious slug alone silently loses every Apple product --
   including the iPhones, which are the most-compared phones in the
   catalogue. Hence the slug TUPLES below.

Saleor exposes a `Category.products` connection that already includes
descendant categories (verified: `konditsionery` totalCount 17 = the sum of
its five brand children), so the sweep asks the parent and gets the brands
for free.
"""
import base64
import logging
from dataclasses import replace
from typing import Iterator

from narxnoma.sources.base import Listing, coerce_price, paginate, try_build_listing
from narxnoma.sources.http import polite_session, post_json

logger = logging.getLogger(__name__)

API_URL = "https://new.api.radius.uz/graphql/"
SITE_URL = "https://radius.uz"
PRODUCT_URL = SITE_URL + "/ru/product/{variant_id}-{slug}"

# category -> radius category slugs, verified live 2026-08-11 by walking the
# whole tree through `categories(level: 0)` and reading every totalCount.
#
#   smartphones  smartfony 77 + the two Apple buckets 7   = 84
#   fridges      kholodilniki                             = 22
#   televisions  televizory                               = 18
#   acs          konditsionery                            = 17
#   washers      stiralnye-mashiny                        = 17
#   laptops      noutbuki 9 + noutbuki-apple 7            = 16
#   ovens        gazovye-plity 12 + dukhovoi-shkaf 1      = 13
#
# The Apple entries are the fragile ones: they are MARKETING buckets
# ("🆕 iPhone 17 | 17 Pro | 17 Pro Max"), not a stable "Смартфоны Apple"
# node, and radius renames them as lines launch. A missing slug here is
# silent -- it looks exactly like a retailer that stopped selling iPhones --
# so test_radius_categories.py asserts this map against the live tree and
# fails when a category with products is not covered by any entry.
#
# Deliberately NOT swept: mikrovolnovye-pechi (9) and mini-pechi (8). Same
# decision as asaxiy, for the same measured reason -- all 540 `ovens` offers
# the other sources contribute contain no microwave, so these could never
# price-compare and would render under the "Духовой шкаф" label.
CATEGORY_SLUGS: dict[str, tuple[str, ...]] = {
    "smartphones": ("smartfony", "iphone-17-17-pro-17-pro-max-air", "iphone-air-3"),
    "televisions": ("televizory",),
    "laptops": ("noutbuki", "noutbuki-apple"),
    "acs": ("konditsionery",),
    "fridges": ("kholodilniki",),
    "washers": ("stiralnye-mashiny",),
    "ovens": ("gazovye-plity", "dukhovoi-shkaf"),
}

PAGE_SIZE = 100

# THE VARIANT IS THE OFFER, not the product. This is the single most important
# decision in this client, and it was measured rather than assumed: the first
# version emitted one listing per Product and 1 of 80 phones attached to a
# canonical variant (1.3%). radius keeps the whole identity on the variant --
#
#   Product.name  "Samsung Galaxy A26"
#   Variant.name  "Смартфон Samsung Galaxy A26 5G 8/256GB Black (Черный)"
#
# -- so the product name has no memory pair and no colour, and a phone key
# needs both. Non-phones were attaching at 100% either way, which is exactly
# why this had to be read per category instead of trusted as an average.
#
# Each variant also has its own price (`priceAmount`), its own stock, and its
# own working URL. Verified live: /ru/product/<non-default variant id>-<slug>
# returns 200 and the page renders THAT colour.
_PRODUCT_FIELDS = """
        id
        name
        slug
        isAvailable
        brand { name }
        category { slug }
        defaultVariant { id }
        variants {
          id
          name
          sku
          priceAmount
          currency
          isAvailable
          quantityAvailable
          thumbnail(size: 512) { url }
        }
        pricing { priceRange { start { amount currency } } }
        thumbnail(size: 512) { url }
"""

CATEGORY_QUERY = """
query CategoryProducts($slug: String!, $first: Int!, $after: String) {
  category(slug: $slug) {
    slug
    products(first: $first, after: $after) {
      totalCount
      pageInfo { hasNextPage endCursor }
      edges { node {%s} }
    }
  }
}
""" % _PRODUCT_FIELDS

SEARCH_QUERY = """
query SearchProducts($search: String!, $first: Int!) {
  products(search: $search, first: $first) {
    edges { node {%s} }
  }
}
""" % _PRODUCT_FIELDS

_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Accept-Language": "ru",
}


def numeric_id(global_id: str | None) -> str | None:
    """Saleor global ids are base64 "Product:5195" / "ProductVariant:8046".

    Returns the numeric part, or None if the value is not a global id we
    recognise. Returning None rather than raising matters: one malformed id
    must cost one listing, not the whole sweep.
    """
    if not global_id:
        return None
    try:
        decoded = base64.b64decode(global_id).decode("utf-8")
    except Exception:                       # noqa: BLE001 - any decode failure
        return None
    kind, _, number = decoded.partition(":")
    if not number.isdigit() or not kind:
        return None
    return number


def _availability(flag) -> str:
    """Saleor's published-and-in-stock flag -> our vocabulary.

    Absent is UNKNOWN rather than OUT_OF_STOCK: an unset field is not evidence
    of a sold-out product.
    """
    return {True: "IN_STOCK", False: "OUT_OF_STOCK"}.get(flag, "UNKNOWN")


def _parse_node(node: dict) -> list[Listing]:
    """One Saleor Product -> one Listing per VARIANT. See _PRODUCT_FIELDS."""
    product_id = numeric_id(node.get("id"))
    slug = node.get("slug")
    if not product_id or not slug:
        return []

    variants = node.get("variants") or []
    if not variants:
        # No variant means no price, no stock and no URL we can trust, and a
        # price we cannot attribute to a specific retailer listing is
        # worthless. Logged rather than dropped in silence: a whole catalogue
        # arriving variant-less is a schema change, not a quiet retailer.
        logger.warning("radius: product %s has no variants; dropping it", product_id)
        return []

    # Product-level fallbacks, for the fields a variant may leave unset.
    product_price = coerce_price(
        (((node.get("pricing") or {}).get("priceRange") or {}).get("start") or {})
        .get("amount"))
    product_image = (node.get("thumbnail") or {}).get("url")

    listings = []
    for variant in variants:
        variant_id = numeric_id(variant.get("id"))
        if not variant_id:
            logger.warning("radius: product %s has a variant with no usable id",
                           product_id)
            continue
        price = coerce_price(variant.get("priceAmount"))
        if price is None:
            price = product_price
        listing = try_build_listing(
            store_slug="radius",
            # The VARIANT id, not the product id: one row per priced,
            # separately-linkable SKU, and source_key is the upsert key.
            source_key=variant_id,
            # The variant name carries the memory pair and the colour; the
            # product name carries neither.
            name_raw=variant.get("name") or node.get("name"),
            price=price,
            url=PRODUCT_URL.format(variant_id=variant_id, slug=slug),
            availability=_availability(
                variant.get("isAvailable")
                if variant.get("isAvailable") is not None
                else node.get("isAvailable")),
            image_url=(variant.get("thumbnail") or {}).get("url") or product_image,
            raw={"product": {k: v for k, v in node.items() if k != "variants"},
                 "variant": variant},
        )
        if listing is not None:
            listings.append(listing)
    return listings


def parse(payload: dict) -> list[Listing]:
    """Turn one GraphQL response into Listings. Pure function, no I/O.

    Works unchanged against either query: the category connection and the
    search connection share the same `edges { node { ... } }` shape, so this
    reads whichever of the two the payload contains.
    """
    data = (payload or {}).get("data") or {}
    connection = data.get("category")
    connection = (connection or {}).get("products") if connection else data.get("products")
    listings = []
    for edge in (connection or {}).get("edges") or []:
        node = (edge or {}).get("node")
        if node:
            listings.extend(_parse_node(node))
    return listings


def next_cursor(payload: dict) -> str | None:
    page_info = ((((payload or {}).get("data") or {}).get("category") or {})
                 .get("products") or {}).get("pageInfo") or {}
    return page_info.get("endCursor") if page_info.get("hasNextPage") else None


class RadiusSource:
    slug = "radius"
    can_sweep = True

    def __init__(self) -> None:
        self._session = None

    def _get_session(self):
        if self._session is None:
            self._session = polite_session(
                referer=f"{SITE_URL}/",
                origin=SITE_URL,
                extra_headers=_HEADERS,
            )
        return self._session

    def _sweep_slug(self, slug: str) -> Iterator[Listing]:
        """One radius category slug, walked with Saleor cursor pagination."""
        session = self._get_session()
        # paginate() drives an integer page counter; Saleor pages by opaque
        # cursor. The cursor is carried here and the counter is used only for
        # paginate's own retry and MAX_PAGES bookkeeping.
        cursor: dict[str, str | None] = {"after": None}

        def fetch(_page):
            return post_json(session, API_URL, json={
                "query": CATEGORY_QUERY,
                "operationName": "CategoryProducts",
                "variables": {"slug": slug, "first": PAGE_SIZE,
                              "after": cursor["after"]},
            })

        def parse_page(payload):
            errors = (payload or {}).get("errors")
            if errors:
                # GraphQL reports failure with HTTP 200 and an `errors` key --
                # exactly the uzum trap documented in docs/parsers/uzum.md.
                # Raising here is what stops a half-swept category being
                # recorded as a successful harvest of nothing.
                raise ValueError(f"radius GraphQL errors for {slug!r}: {errors}")
            if ((payload.get("data") or {}).get("category")) is None:
                raise ValueError(f"radius: no such category {slug!r}")
            return parse(payload)

        def following(payload, page):
            after = next_cursor(payload)
            if after is None:
                return None
            cursor["after"] = after
            return page + 1

        yield from paginate(fetch, parse_page, following)

    def sweep(self, category: str = "smartphones") -> Iterator[Listing]:
        """Every product in one of our categories, across radius's slugs for it."""
        slugs = CATEGORY_SLUGS.get(category)
        if slugs is None:
            raise ValueError(f"unknown category {category!r}")

        # A product can legitimately sit under two of the slugs we sweep for
        # one category (Saleor's Category.products includes descendants, and
        # the Apple buckets overlap), and source_key is the upsert key -- so
        # the same product arriving twice would be counted twice in
        # HarvestResult while writing one row.
        seen: set[str] = set()
        for slug in slugs:
            for listing in self._sweep_slug(slug):
                if listing.source_key in seen:
                    continue
                seen.add(listing.source_key)
                yield (replace(listing, category=category)
                       if listing.category != category else listing)

    def search(self, query: str) -> Iterator[Listing]:
        """Saleor's `products(search:)`. Present for the Source protocol; the
        harvest uses sweep(), and Pass B only queries sources that cannot be
        swept."""
        session = self._get_session()
        payload = post_json(session, API_URL, json={
            "query": SEARCH_QUERY,
            "operationName": "SearchProducts",
            "variables": {"search": query, "first": PAGE_SIZE},
        })
        yield from parse(payload)
