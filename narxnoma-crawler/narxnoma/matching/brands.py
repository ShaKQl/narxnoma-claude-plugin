"""Brand vocabulary and per-brand policy.

Single home for anything brand-specific, because three modules need it:
memory.py (who publishes RAM), features.py (alias resolution) and keys.py
(key completeness + display label).
"""

# TWO ROLES, WITH OPPOSITE FAILURE MODES -- read this before removing an entry.
#
# 1. RECOGNITION vocabulary for extract_features. A brand missing here degrades
#    ONE listing's identity.
# 2. CRAWL FRONTIER, via narxnoma.sources.brand_queries. idea, alifshop and
#    uzum have no browsable catalogue endpoint, so this list is their ENTIRE
#    reach. A brand missing here is not a degraded name -- it is ZERO OFFERS,
#    permanently, from three of seven sources, and nothing in the system
#    reports the absence of something never looked for.
#
# So this list is cheap to extend and expensive to trim. Adding a brand nobody
# sells costs one wasted query per cycle; omitting one costs its whole catalogue.

# Order matters: matched as substrings, so sub-brands come before parents.
BRANDS: list[str] = [
    "apple", "samsung", "honor", "xiaomi", "vivo", "oppo", "realme",
    "tecno", "infinix", "nothing", "google", "asus", "huawei",
    "motorola", "zte", "meizu",
    "itel", "nokia", "oneplus", "nubia", "tcl", "blackview", "doogee",
    "ulefone",
]

BRAND_ALIASES: dict[str, str] = {
    "iphone": "apple",
    "redmi": "xiaomi",
    "poco": "xiaomi",
}

# Brands that never print RAM in consumer product names. For these, RAM is
# absent rather than unknown, so a key without RAM is still complete.
BRANDS_WITHOUT_PUBLISHED_RAM: frozenset[str] = frozenset({"apple"})

BRAND_LABELS: dict[str, str] = {
    "apple": "Apple iPhone",   # "iphone" is stripped as a NON_MODEL_TOKEN
    "samsung": "Samsung",
    "honor": "Honor",
    "xiaomi": "Xiaomi",
    "vivo": "Vivo",
    "oppo": "OPPO",
    "realme": "Realme",
    "tecno": "Tecno",
    "infinix": "Infinix",
    "nothing": "Nothing",
    "google": "Google",
    "asus": "ASUS",
    "huawei": "Huawei",
    "motorola": "Motorola",
    "zte": "ZTE",
    "meizu": "Meizu",
    "itel": "Itel",
    "nokia": "Nokia",
    "oneplus": "OnePlus",
    "nubia": "Nubia",
    "tcl": "TCL",
    "blackview": "Blackview",
    "doogee": "Doogee",
    "ulefone": "Ulefone",
}


def canonical_brand(token: str) -> str:
    """Collapse a sub-brand to its parent ('redmi' -> 'xiaomi')."""
    return BRAND_ALIASES.get(token, token)
