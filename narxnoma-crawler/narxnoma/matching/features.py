"""Feature extraction: normalised name -> structured identity."""
import re
from dataclasses import dataclass

from narxnoma.matching.brands import BRAND_ALIASES, BRANDS, canonical_brand
from narxnoma.matching.colors import COLOR_MAP, QUALIFIERS, colors_in_order, primary_color
from narxnoma.matching.memory import scan_memory
from narxnoma.matching.normalize import normalize

# "galaxy" is deliberately absent: mediapark lists the A07 as
# "SAMSUNG SM-A075F A07" with no "Galaxy". Identity comes from a07/a17/s26.
MODEL_MODIFIERS: frozenset[str] = frozenset({
    "pro", "ultra", "lite", "plus", "max", "mini", "note", "redmi",
    "air", "fe", "se",          # genuine designators, not marketing words
    # Family words for the Galaxy Z line. Without them both "Galaxy Z Fold 7"
    # and "Galaxy Z Flip 7" reduce to model_tokens={'7'} and collapse onto the
    # identical key samsung-7-12-256-black, merging two products whose prices
    # differ by roughly a factor of two.
    "fold", "flip",
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

    ram, storage, stated_ram = scan_memory(name, n, brand)

    tokens = n.split()
    token_set = set(tokens)
    colors = frozenset(colors_in_order(tokens))
    primary = primary_color(tokens)

    # stated_ram is reserved as well as ram. For Apple, ram is suppressed to
    # None (Apple publishes no RAM), but the figure the reseller wrote is
    # still a memory figure -- without reserving it, "iPhone 17 Pro 12/256GB"
    # keeps "12" as a MODEL token and keys as apple-12-17-pro-256-silver,
    # which splits the product exactly as the RAM did and additionally
    # hard-rejects the listing on the reverse model-token check.
    reserved = {str(storage or ""), str(ram or ""), str(stated_ram or ""), "5g", "4g", "0"}
    model_tokens: set[str] = set()
    for t in token_set:
        if t in NON_MODEL_TOKENS or t in COLOR_MAP or t in QUALIFIERS or t in reserved:
            continue
        if re.fullmatch(r"\d+(?:gb|гб|tb|тб)", t):
            continue
        # Skip SKU/catalogue codes (letters+digits, len >= 5): "a075f",
        # "sm-a175f", and spec-blurb fragments like "120hz", "200mp", "6500mah".
        #
        # 5 is measured, not guessed. Across all 14,860 golden rows, accept/reject
        # agreement is 99.993% at 5 and 99.987% at 6, 7, 8 and with the rule off
        # entirely -- raising it is strictly worse. At 6 the rule stops discarding
        # 5-character mixed tokens, so "120hz" and "200mp" survive as model tokens
        # and then reject a legitimate Redmi Note 15 Pro match: the marketing-blurb
        # failure uzum.md section 5a exists to prevent, recreated by loosening the
        # rule that prevents it. See test_sku_min_len_is_measured_not_guessed.
        #
        # KNOWN GAP: this also discards real designators of 5+ characters --
        # "reno15", "magic8", "fold4". Those products are currently unkeyable. The
        # fix is a targeted designator allowlist applied BEFORE this rule, not a
        # different threshold; length cannot separate the two populations, because
        # real designators and catalogue codes overlap in length.
        if len(t) >= _SKU_MIN_LEN and any(c.isalpha() for c in t) and any(c.isdigit() for c in t):
            continue
        if any(c.isdigit() for c in t):
            if t.isdigit() and int(t) in {
                (storage or -1), (ram or -1), (stated_ram or -1)
            }:
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
