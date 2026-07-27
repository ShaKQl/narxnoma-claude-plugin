"""Brand vocabulary and per-brand policy.

Single home for anything brand-specific, because three modules need it:
memory.py (who publishes RAM), features.py (alias resolution) and keys.py
(key completeness + display label).
"""

# Order matters: matched as substrings, so sub-brands come before parents.
BRANDS: list[str] = [
    "apple", "samsung", "honor", "xiaomi", "vivo", "oppo", "realme",
    "tecno", "infinix", "nothing", "google", "asus", "huawei",
    "motorola", "zte", "meizu",
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
}


def canonical_brand(token: str) -> str:
    """Collapse a sub-brand to its parent ('redmi' -> 'xiaomi')."""
    return BRAND_ALIASES.get(token, token)
