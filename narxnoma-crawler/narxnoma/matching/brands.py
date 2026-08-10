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
    # Third measured pass, 2026-08-10, prompted by asaxiy: 63 of its 693
    # offers had no identity at all, and the same head words were failing for
    # uzum, olcha, idea and alifshop too -- 873 non-phone offers in total.
    # Same method again: count the unrecognised head token across every
    # unresolved title, confirm each against real listings as a maker.
    #
    # Counted before adding (hits / stores that publish them):
    #   gree 38/3   atlant 25/1   keetab 11/2   chuwi 10/4   konnen 10/3
    #   jpe 9/1     ario 9/1      qlt 8/1       magna 8/2    ssmart 8/2
    #   huamei 7/1  lunix 7/1     caderno 6/1   apetito 5/1  adreamer 5/1
    #   vitech 4/1  beston 4/1    chigo 4/1     microsoft 4/2  aufit 3/2
    #
    # NOT added, and why: "lrf" (7, idea: "LRF-456GS") and "gtw" (4, idea:
    # "GTW-734") are code prefixes whose manufacturer no listing anywhere in
    # the catalogue spells out -- unlike "prm" and "shiv" below, which are
    # confirmed. Guessing a brand is how two different products become one
    # page. "rivacase" (7, texnomart) is real, and its listings are laptop
    # BAGS ("Noutbuk sumkasi"); leaving it unrecognised is what keeps them
    # out of the laptop catalogue.
    "gree", "atlant", "keetab", "chuwi", "konnen", "jpe", "ario", "qlt",
    "magna", "ssmart", "huamei", "lunix", "caderno", "apetito", "adreamer",
    "vitech", "beston", "chigo", "microsoft", "aufit",
    # Two characters, which is why the head-token count above never saw it: a
    # 2-char token was skipped as too short to be a name. Found by counting
    # them separately. BQ's 55FU32B and 43FS36B are each carried by asaxiy,
    # uzum and alifshop -- two real three-store comparisons that were lost.
    "bq",
    # laptops
    "lenovo", "acer", "msi", "dell", "bikon", "gigabyte", "razer",
    "hp",
]

# Aliases that apply OUTSIDE smartphones only.
#
# Kept separate from BRAND_ALIASES because that dict has two other jobs: it is
# probed first in the phone path's plain SUBSTRING scan (pinned by 14,860
# golden rows), and it feeds BRAND_QUERIES, the phone crawl frontier -- so an
# appliance alias added there would spend a real query per cycle at three
# retailers asking for a phone brand that does not exist.
#
# Each entry confirmed against listings that spell the brand out in full:
APPLIANCE_BRAND_ALIASES: dict[str, str] = {
    # A BUG, not a gap: "biryusa" was added to the vocabulary in the Latin
    # spelling and its own display label is "Бирюса" -- but every listing
    # writes it in Cyrillic, and normalize() leaves an all-Cyrillic token
    # alone (correctly: there is no Latin in it to fold). 20 offers across
    # asaxiy and uzum were unkeyable because the two spellings never met.
    "бирюса": "biryusa",
    # Premier prefixes its codes "PRM-", and idea drops the brand word
    # entirely: "PRM-350TFNFID/DI". Confirmed by uzum's "Холодильник Premier
    # PRM-250TFDF/W", which carries both.
    "prm": "premier",
    # Same shape for Shivaki: uzum publishes both "Стиральная машина SHIVAKI
    # SHIV-WM 1108 Sentaku" and "Стиральная машина SHIV-WM 1106 Sentaku",
    # and alifshop's "Shivaki WM1106 S Sentaku" names the same line.
    "shiv": "shivaki",
    # A misspelling on uzum, not a second brand: "Газовые плиты Zifler Breeze
    # Series BGS-6031BE" is Ziffler's Breeze line, which uzum also lists
    # correctly spelled.
    "zifler": "ziffler",
    # idea and alifshop write "Konnen", the brand writes "KÖNNEN", and
    # normalize() keeps the umlaut.
    "können": "konnen",
}

#: Alias resolution for non-phone categories: the phone aliases still apply
#: (a MacBook is an Apple laptop) plus the appliance-only ones above.
NON_PHONE_ALIASES: dict[str, str] = {**BRAND_ALIASES, **APPLIANCE_BRAND_ALIASES}

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
    "gree": "Gree", "atlant": "ATLANT", "keetab": "Keetab", "chuwi": "CHUWI",
    "konnen": "Konnen", "jpe": "JPE", "ario": "ARIO", "qlt": "QLT",
    "magna": "Magna", "ssmart": "Ssmart", "huamei": "Huamei",
    "lunix": "Lunix", "caderno": "Caderno", "apetito": "Apetito",
    "adreamer": "Adreamer", "vitech": "Vitech", "beston": "Beston",
    "chigo": "Chigo", "microsoft": "Microsoft", "aufit": "Aufit",
    "bq": "BQ",
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


def canonical_non_phone_brand(token: str) -> str:
    """Collapse an appliance sub-brand or code prefix ('prm' -> 'premier').

    Separate from canonical_brand rather than a category flag on it, so the
    phone path -- a plain substring scan pinned by 14,860 golden rows -- keeps
    resolving through BRAND_ALIASES and nothing else.
    """
    return NON_PHONE_ALIASES.get(token, token)


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
