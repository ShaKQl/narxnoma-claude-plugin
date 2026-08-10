"""Feature extraction: normalised name -> structured identity."""
import re
from dataclasses import dataclass

from narxnoma.matching.brands import (
    BRAND_ALIASES,
    BRANDS,
    NON_PHONE_ALIASES,
    NON_PHONE_BRANDS,
    canonical_brand,
    canonical_non_phone_brand,
)
from narxnoma.matching.categories import (
    CATEGORIES_WITH_MEMORY,
    cut_at_processor,
    head_for_model,
    is_model_token,
)
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

# Probed with WORD BOUNDARIES, unlike the phone list below, which is a plain
# substring scan. The appliance vocabulary contains genuinely short names --
# "lg", "arg", "hp" -- and a substring scan finds "arg" inside "charger" and
# "large". A trailing digit still counts as a boundary so the glued "Hp15-fd00"
# that idea and olcha both publish is recognised.
#
# ...except for these, where the same allowance reads a brand out of somebody
# else's SKU. Adding "bq" for BQ's televisions relabelled two ASUS laptops:
#     "Ноутбук ASUS VivoBook X1502VA-BQ827 / i7-13620H / DDR4 16GB / ..."
#     "ASUS Vivobook 15 X1502VA-BQ982 i7-13620H/16/512GB Cool Silver"
# "-BQ827" is ASUS's own suffix, normalize() splits the hyphen to "bq827", and
# the trailing-digit boundary matched it -- so both machines were keyed as a BQ
# and merged with each other. Caught by reading every multi-store variant the
# change produced, which is the only thing that can catch a substitution: the
# result looked exactly like a healthy two-store match.
#
# A strict boundary still finds the televisions ("Телевизор BQ 43FS36B" has
# "bq" as its own token) and no longer finds the ASUS suffix. Two characters
# is the real problem -- there are simply more SKUs containing "bq" than
# containing "hofmann" -- but "hp" and "lg" are two characters as well and
# their digit-glued forms are measured and real, so this is an opt-out per
# brand rather than a rule about length.
_NO_DIGIT_GLUE: frozenset[str] = frozenset({"bq"})

_NON_PHONE_PROBE_ORDER: list[str] = list(NON_PHONE_ALIASES) + NON_PHONE_BRANDS
_NON_PHONE_BRAND_RE: dict[str, re.Pattern[str]] = {
    b: re.compile(rf"\b{re.escape(b)}\b" if b in _NO_DIGIT_GLUE
                  else rf"\b{re.escape(b)}(?=\b|\d)")
    for b in _NON_PHONE_PROBE_ORDER
}


def _detect_brand(n: str, category: str) -> str | None:
    """Brand from a normalised name.

    The phone path is left EXACTLY as it was -- a substring scan in the
    documented probe order -- because 14,860 golden rows pin its behaviour and
    this change is not the place to move it.
    """
    if category == "smartphones":
        for b in _BRAND_PROBE_ORDER:
            if b in n:
                return canonical_brand(b)
        return None
    for b in _NON_PHONE_PROBE_ORDER:
        if _NON_PHONE_BRAND_RE[b].search(n):
            return canonical_non_phone_brand(b)
    return None


def _non_phone_model_tokens(
    name: str | None, brand: str | None, reserved: set[str],
    category: str = "laptops",
) -> set[str]:
    """Identity tokens for a TV, laptop, fridge, AC, washer or oven.

    Reads the HEAD of the title only (see categories.head_for_model): a
    laptop's specification follows a delimiter and is not part of its name.
    Memory and colour were already taken from the whole title by the caller,
    so truncating here costs no identity field.

    `category` reaches the two processor rules and nothing else -- a CPU name
    is a specification on a computer and a model name on an air conditioner.
    See categories.CATEGORIES_WITH_CPU.
    """
    head = normalize(head_for_model(name or ""))
    tokens = set(cut_at_processor(head.split(), category))
    known_brands = set(_NON_PHONE_PROBE_ORDER)
    out: set[str] = set()
    for t in tokens:
        # The brand is an axis of the key already; repeating it inside
        # model_tokens would let "LG" and "LG LG" become two products.
        if t in known_brands or canonical_non_phone_brand(t) == brand:
            continue
        if t in NON_MODEL_TOKENS or t in COLOR_MAP or t in QUALIFIERS:
            continue
        if t in reserved:
            continue
        if _CYRILLIC_WORD.fullmatch(t):
            # An appliance's model name is written in Latin -- "Shaxrisabz",
            # "Naomi Pro", "Frost", "HD276FND". A Cyrillic WORD in the title is
            # descriptive: a colour or finish the palette does not know
            # ("Матовый", "Асфальт", "Мокрый"), or a Russian abbreviation for
            # the appliance type ("Кп" for комбинированная плита, "Гп" for
            # газовая плита).
            #
            # MEASURED: those three finish words alone split one fridge into
            # three products -- "Artel Frost HD276FND", "... Матовый ...", and
            # "... Асфальт Мокрый ..." -- at three different prices. Colour is
            # deliberately NOT identity outside phones, so a colour word that
            # merely escaped the palette must not become identity by accident.
            #
            # Enumerating every finish word cannot work: retailers invent them.
            # The script is the reliable signal, and the failure direction is
            # safe -- a product genuinely named in Cyrillic keeps its brand and
            # any Latin tokens, and becomes unkeyable only if it has none.
            continue
        if not is_model_token(t, category):
            continue
        out.add(t)
    return _collapse_to_catalogue_code(out)


_CYRILLIC_WORD = re.compile(r"[а-я]+")

# A manufacturer's catalogue code identifies exactly one product -- that is
# what it is FOR. Seven characters is the floor measured across the live
# catalogue: every real code observed is at least eight ("HD276FND",
# "B392SMBB", "RT62K7110SL", "UE55DU7100UXUZ", "ARTSID3AW12BE"), while the
# spec fragments that must not be mistaken for one are shorter ("i7", "16s",
# "1255u", "a315", "ddr5").
_CODE_MIN_LEN = 7


def _is_catalogue_code(token: str) -> bool:
    return (
        len(token) >= _CODE_MIN_LEN
        and any(c.isdigit() for c in token)
        and any(c.isalpha() for c in token)
    )


def _collapse_to_catalogue_code(tokens: set[str]) -> set[str]:
    """When a title states a catalogue code, the code IS the identity.

    Retailers decorate the same code differently, and every decoration became
    a separate product. All of these are ONE Samsung fridge:

        "Холодильник Samsung RB29FERNDSA"
        "Холодильник Samsung 290L RB29FERNDSA"     (capacity)
        "Холодильник Samsung Inox RT62K7110SL"     (finish, in Latin)
        "Холодильник LG Apzqcis Gn B392SMBB"       (an internal code fragment)
        "Кондиционер Artel Everest ARTSID3AW12BE"  (product line)

    Measured before this rule: 1,235 pairs where one variant's tokens were a
    strict subset of another's in the same brand and category. The code cannot
    collide -- two different products never share one -- so collapsing onto it
    can only merge listings that genuinely are the same product.

    A title with NO code keeps all its tokens: "Телевизор MoonX 32" and
    "Кондиционер Midea Naomi Pro 09" have nothing else to be identified by.
    """
    codes = {t for t in tokens if _is_catalogue_code(t)}
    return codes or tokens


@dataclass(frozen=True)
class Features:
    brand: str | None
    ram_gb: int | None
    storage_gb: int | None
    colors: frozenset[str]
    primary_color: str | None
    model_tokens: frozenset[str]
    normalized: str


def extract_features(name: str | None, category: str = "smartphones") -> Features:
    """Normalised name -> structured identity.

    `category` selects the identity model. It defaults to smartphones so every
    existing caller, test and golden-corpus row keeps the exact behaviour it
    had; the non-phone branch is additive. See categories.py for why a
    television cannot be read with a phone's rules.
    """
    normalized = normalize(name)
    n = _PREFIX_NOISE.sub("", normalized).strip()
    n = re.sub(r"\s+", " ", n)

    brand = _detect_brand(n, category)

    ram, storage, stated_ram = scan_memory(name, n, brand)

    tokens = n.split()
    token_set = set(tokens)
    colors = frozenset(colors_in_order(tokens))
    primary = primary_color(tokens)

    # stated_ram is reserved as well as ram -- see the note on the phone path
    # below for why. Both branches share the set.
    reserved_figures = {
        str(storage or ""), str(ram or ""), str(stated_ram or ""),
        "5g", "4g", "0",
    }

    if category != "smartphones":
        if category not in CATEGORIES_WITH_MEMORY:
            # Not "unknown" -- ABSENT. A television has no RAM and no SSD, so a
            # figure that looks like one is a diagonal or a litre capacity that
            # happened to land in the plausible-storage set.
            ram = storage = None
            reserved_figures = {"5g", "4g", "0"}
        return Features(
            brand=brand,
            ram_gb=ram,
            storage_gb=storage,
            colors=colors,
            primary_color=primary,
            model_tokens=frozenset(
                _non_phone_model_tokens(name, brand, reserved_figures, category)
            ),
            normalized=n,
        )

    # stated_ram is reserved as well as ram. For Apple, ram is suppressed to
    # None (Apple publishes no RAM), but the figure the reseller wrote is
    # still a memory figure -- without reserving it, "iPhone 17 Pro 12/256GB"
    # keeps "12" as a MODEL token and keys as apple-12-17-pro-256-silver,
    # which splits the product exactly as the RAM did and additionally
    # hard-rejects the listing on the reverse model-token check.
    reserved = reserved_figures
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
