"""Canonical brand-query vocabulary, shared by every source with no
browsable catalogue.

idea.uz and alifshop.uz both have no full-catalogue browse endpoint, so
both sweep by issuing one search per brand instead of walking a category
endpoint -- and both need the exact same list, so it lives here once
rather than being copy-pasted per client. It is the project's canonical
brand vocabulary (narxnoma.matching.brands.BRANDS) plus alias keys
(narxnoma.matching.brands.BRAND_ALIASES) such as "redmi", "poco",
"iphone": a retailer lists "Redmi Note 15" with no "Xiaomi" anywhere in
the name, so querying only the parent brand would miss it.

Any source using this list has no other reach into the catalogue -- a
brand missing here is permanently invisible to it -- so this must never
be hand-maintained separately from narxnoma.matching.brands; deriving it
here means a brand added there becomes visible to every sweep that uses
this module automatically. Sorted for determinism.
"""
from narxnoma.matching.brands import BRAND_ALIASES, BRANDS

BRAND_QUERIES: tuple[str, ...] = tuple(sorted(set(BRANDS) | set(BRAND_ALIASES)))
