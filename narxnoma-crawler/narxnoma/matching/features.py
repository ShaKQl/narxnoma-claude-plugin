"""Feature extraction: normalised name -> structured identity."""
import re
from dataclasses import dataclass

from narxnoma.matching.brands import BRAND_ALIASES, BRANDS, canonical_brand
from narxnoma.matching.colors import COLOR_MAP, QUALIFIERS, colors_in_order, primary_color
from narxnoma.matching.memory import extract_memory
from narxnoma.matching.normalize import normalize

# "galaxy" is deliberately absent: mediapark lists the A07 as
# "SAMSUNG SM-A075F A07" with no "Galaxy". Identity comes from a07/a17/s26.
MODEL_MODIFIERS: frozenset[str] = frozenset({
    "pro", "ultra", "lite", "plus", "max", "mini", "note", "redmi",
    "air", "fe", "se",          # genuine designators, not marketing words
})

NON_MODEL_TOKENS: frozenset[str] = frozenset({
    "gb", "гб", "tb", "тб", "smartfon", "смартфон", "iphone",
    "apple", "samsung", "honor", "xiaomi", "vivo", "oppo", "realme",
    "tecno", "infinix", "poco", "nothing", "google", "asus", "huawei",
    "motorola", "zte", "meizu",
    "esim", "nanosim", "sim", "nano", "point",
    "rang", "smartfoni", "telefon", "chidamli", "zarbaga",   # uz filler
})

# Sub-brands must be probed BEFORE their parents, so a "Redmi Note 15" is
# recognised by "redmi" rather than falling through to a bare "xiaomi".
_BRAND_PROBE_ORDER: list[str] = list(BRAND_ALIASES) + BRANDS

_SKU_MIN_LEN = 5
_PREFIX_NOISE = re.compile(r"\b(смартфон|smartfon\w*)\b")


@dataclass(frozen=True)
class Features:
    brand: str | None
    ram_gb: int | None
    storage_gb: int | None
    colors: frozenset[str]
    primary_color: str | None
    model_tokens: frozenset[str]
    normalized: str


def extract_features(name: str | None) -> Features:
    normalized = normalize(name)
    n = _PREFIX_NOISE.sub("", normalized).strip()
    n = re.sub(r"\s+", " ", n)

    brand = None
    for b in _BRAND_PROBE_ORDER:
        if b in n:
            brand = canonical_brand(b)
            break

    ram, storage = extract_memory(name, n, brand)

    tokens = n.split()
    token_set = set(tokens)
    colors = frozenset(colors_in_order(tokens))
    primary = primary_color(tokens)

    reserved = {str(storage or ""), str(ram or ""), "5g", "4g", "0"}
    model_tokens: set[str] = set()
    for t in token_set:
        if t in NON_MODEL_TOKENS or t in COLOR_MAP or t in QUALIFIERS or t in reserved:
            continue
        if re.fullmatch(r"\d+(?:gb|гб|tb|тб)", t):
            continue
        # Skip SKU/catalogue codes (letters+digits, len >= 5): "a075f",
        # "sm-a175f". Real designators (a07, a17, x9d, y31d) are <= 4 chars.
        if len(t) >= _SKU_MIN_LEN and any(c.isalpha() for c in t) and any(c.isdigit() for c in t):
            continue
        if any(c.isdigit() for c in t):
            if t.isdigit() and int(t) in {(storage or -1), (ram or -1)}:
                continue
            model_tokens.add(t)
        elif t in MODEL_MODIFIERS:
            model_tokens.add(t)

    return Features(
        brand=brand,
        ram_gb=ram,
        storage_gb=storage,
        colors=colors,
        primary_color=primary,
        model_tokens=frozenset(model_tokens),
        normalized=n,
    )
