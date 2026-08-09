"""Canonical brand-query vocabulary: the CRAWL FRONTIER for every source with
no browsable catalogue.

idea.uz, alifshop.uz and uzum.uz have no full-catalogue browse endpoint, so
they sweep by issuing one search per brand instead of walking a category
endpoint -- and all three need the exact same list, so it lives here once
rather than being copy-pasted per client. It is the project's canonical
brand vocabulary (narxnoma.matching.brands.BRANDS) plus alias keys
(narxnoma.matching.brands.BRAND_ALIASES) such as "redmi", "poco",
"iphone": a retailer lists "Redmi Note 15" with no "Xiaomi" anywhere in
the name, so querying only the parent brand would miss it.

This list is a crawl frontier, not just a recognition vocabulary, and the
two roles have opposite failure modes:

1. RECOGNITION (narxnoma.matching.brands / extract_features): a brand
   missing there degrades ONE listing's identity.
2. CRAWL FRONTIER (this module): a brand missing HERE is ZERO OFFERS,
   permanently, from three of seven sources -- and nothing in the system
   reports the absence of something never looked for.

So the vocabulary is cheap to extend and expensive to trim: adding a brand
nobody sells costs one wasted query per cycle; omitting one costs its whole
catalogue. For the same reason this must never be hand-maintained separately
from narxnoma.matching.brands; deriving it here means a brand added there
becomes visible to every sweep that uses this module automatically. Sorted
for determinism.
"""
from narxnoma.matching.brands import BRAND_ALIASES, BRANDS

BRAND_QUERIES: tuple[str, ...] = tuple(sorted(set(BRANDS) | set(BRAND_ALIASES)))
