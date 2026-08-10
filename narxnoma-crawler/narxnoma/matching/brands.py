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
    "macbook": "apple",
    # Avalon prefixes its model codes "AVL-": "AVALON AVL-RF512", and some
    # listings drop the brand word entirely ("Стиральная машина AVL-WM 7030").
    "avl": "avalon",
}

# Brands that appear ONLY outside smartphones: TV, appliance and laptop makers.
#
# MEASURED, not guessed. Every entry here was read off the live catalogue: the
# 2,076 non-phone offers were normalised, their category noun stripped, and the
# remaining head token counted. Each token below was then confirmed by eye
# against three real listings as a manufacturer rather than a descriptor --
# which is why "полуавтомат" (28 hits), "двухкамерный", "сплит-система" and
# "игровой" are NOT here: they describe the appliance, they do not make it.
#
# Kept SEPARATE from BRANDS on purpose. BRANDS doubles as the crawl frontier
# (see above), and querying uzum/alifshop/idea for "bosch" under a *phone*
# sweep would spend requests on a brand that sells no phones. These are
# recognition-only; the category sweeps reach them by category, not by brand.
APPLIANCE_BRANDS: list[str] = [
    # TV / large appliance
    "artel", "premier", "hisense", "shivaki", "ziffler", "wellstars",
    "toshiba", "panasonic", "hikvision", "alpicool", "texnowell",
    "avalon", "brando", "moonx", "mytech", "meiga", "immer", "sonor",
    "volto", "konig", "rosso", "rulls", "vesta", "frame", "litv",
    "haier", "midea", "bosch", "beko", "indesit", "whirlpool", "gorenje",
    "electrolux", "ariston", "siemens", "candy", "roison", "ferre",
    "sony", "philips", "sharp", "supra", "yasin", "goldstar",
    "7tech", "arg", "lg",
    # Second measured pass, after the category frontier tripled the non-phone
    # catalogue (2,076 -> 6,320 offers). Same method: unrecognised head tokens
    # counted across every non-phone title, each confirmed against three real
    # listings as a manufacturer.
    "hofmann", "gefest", "elite", "aux", "ideal", "loretto", "bench",
    "kleo", "sitronic", "volna", "itech", "goodwell", "helper", "aiwa",
    "sirius", "biryusa", "sencor", "vestel", "zanussi", "hansa",
    # laptops
    "lenovo", "acer", "msi", "dell", "bikon", "gigabyte", "razer",
    "hp",
]

#: Recognition vocabulary for non-phone categories: appliance makers plus the
#: phone brands that also sell TVs, laptops and white goods (Samsung, Apple,
#: Xiaomi, Honor, Huawei, ASUS, TCL all do).
NON_PHONE_BRANDS: list[str] = APPLIANCE_BRANDS + BRANDS

APPLIANCE_BRAND_LABELS: dict[str, str] = {
    "artel": "Artel", "premier": "Premier", "hisense": "Hisense",
    "shivaki": "Shivaki", "ziffler": "Ziffler", "wellstars": "WellStars",
    "toshiba": "Toshiba", "panasonic": "Panasonic", "hikvision": "Hikvision",
    "alpicool": "Alpicool", "texnowell": "Texnowell", "avalon": "Avalon",
    "brando": "Brando", "moonx": "MoonX", "mytech": "Mytech",
    "meiga": "Meiga", "immer": "Immer", "sonor": "Sonor", "volto": "Volto",
    "konig": "Konig", "rosso": "Rosso", "rulls": "Rulls", "vesta": "Vesta",
    "frame": "Frame", "litv": "LiTV", "haier": "Haier", "midea": "Midea",
    "bosch": "Bosch", "beko": "Beko", "indesit": "Indesit",
    "whirlpool": "Whirlpool", "gorenje": "Gorenje",
    "electrolux": "Electrolux", "ariston": "Ariston", "siemens": "Siemens",
    "candy": "Candy", "roison": "Roison", "ferre": "Ferre", "sony": "Sony",
    "philips": "Philips", "sharp": "Sharp", "supra": "Supra",
    "yasin": "Yasin", "goldstar": "Goldstar", "7tech": "7Tech",
    "arg": "ARG", "lg": "LG", "lenovo": "Lenovo", "acer": "Acer",
    "msi": "MSI", "dell": "Dell", "bikon": "BIKON", "gigabyte": "Gigabyte",
    "razer": "Razer", "hp": "HP",
    "hofmann": "Hofmann", "gefest": "Gefest", "elite": "Elite",
    "aux": "AUX", "ideal": "Ideal", "loretto": "Loretto", "bench": "Bench",
    "kleo": "Kleo", "sitronic": "Sitronic", "volna": "Volna",
    "itech": "iTech", "goodwell": "Goodwell", "helper": "Helper",
    "aiwa": "AIWA", "sirius": "Sirius", "biryusa": "Бирюса",
    "sencor": "Sencor", "vestel": "Vestel", "zanussi": "Zanussi",
    "hansa": "Hansa",
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


def brand_label(brand: str, category: str = "smartphones") -> str:
    """Display label for a brand, in the context of a category.

    Category matters for exactly one entry, and getting it wrong is visible to
    every user: BRAND_LABELS maps "apple" to "Apple iPhone", because for phones
    the word "iPhone" is stripped as a NON_MODEL_TOKEN and has to be put back.
    A MacBook is also brand "apple", so the phone label would render
    "Ноутбук Apple iPhone MacBook Air" on a laptop page.
    """
    if category != "smartphones":
        if brand in APPLIANCE_BRAND_LABELS:
            return APPLIANCE_BRAND_LABELS[brand]
        if brand == "apple":
            return "Apple"
        return BRAND_LABELS.get(brand, brand.capitalize())
    return BRAND_LABELS.get(brand, brand.capitalize())
