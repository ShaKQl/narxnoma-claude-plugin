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

# --- category frontier -------------------------------------------------------
#
# BRAND_QUERIES is a PHONE frontier, and using it for a category sweep is why
# uzum held 2,381 phones and ZERO air conditioners, fridges, washers or ovens:
# the sweep queried "apple", "samsung", "xiaomi" ... and then filtered the
# results down to category id 82. Two things defeat that.
#
# 1. The brands that sell white goods here -- Artel, Premier, Shivaki, LG,
#    Hisense, Bosch -- sell no phones, so they are not in BRAND_QUERIES at all
#    and were never queried.
# 2. Even for Samsung, which sells both, relevance ranks phones first and
#    pagination caps at offset 1000, so a fridge never surfaces.
#
# A category sweep therefore needs its own frontier: the product noun the
# retailer's own customers type, in Russian and Uzbek (Latin), plus the brands
# that actually sell in that category. The noun does the work -- one query
# reaches the whole category -- and the brand queries are there for products
# whose titles omit the noun entirely, which the live catalogue does contain
# ("Artel UA43H3502 Android TV", "SAMSUNG RB29FERNDSA 290L Sovutgichi").
#
# Deliberately NOT the full appliance vocabulary: 50 brands x 6 categories is
# 300 queries a cycle for a handful of extra listings. These are the brands
# measured as actually present in each category in the live catalogue.
_WHITE_GOODS = ("artel", "premier", "shivaki", "samsung", "lg", "bosch")

CATEGORY_QUERIES: dict[str, tuple[str, ...]] = {
    "televisions": (
        "televizor", "телевизор",
        "artel", "premier", "samsung", "lg", "hisense", "shivaki", "vesta",
    ),
    "laptops": (
        "noutbuk", "ноутбук", "laptop",
        "asus", "acer", "hp", "lenovo", "apple", "msi", "dell",
    ),
    "acs": (
        "konditsioner", "кондиционер", "split",
        "artel", "premier", "shivaki", "lg", "hisense", "midea",
    ),
    # "muzlatgich" is LAST on purpose: on uzum it resolves to freezers, not
    # refrigerators (verified live). "холодильник" and "sovutgich" are the
    # words that reach the refrigerator category, while other retailers do use
    # "Muzlatgichi" for a fridge, so it stays in the frontier.
    "fridges": (
        "холодильник", "sovutgich", "muzlatgich",
        *_WHITE_GOODS,
    ),
    "washers": (
        "kir yuvish mashinasi", "стиральная машина",
        *_WHITE_GOODS,
    ),
    "ovens": (
        "duxovka", "духовой шкаф", "газовая плита", "pech",
        *_WHITE_GOODS,
    ),
}


def queries_for(category: str) -> tuple[str, ...]:
    """The crawl frontier for one category.

    Phones keep the brand frontier they have always used; every other category
    gets the noun-led frontier above. A source that filters its results by a
    category id still needs this, because filtering can only remove what the
    query already returned.
    """
    if category == "smartphones":
        return BRAND_QUERIES
    try:
        return CATEGORY_QUERIES[category]
    except KeyError:
        raise ValueError(f"no crawl frontier for category {category!r}") from None
