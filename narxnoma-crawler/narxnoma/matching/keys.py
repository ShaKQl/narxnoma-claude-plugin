"""Canonical variant identity.

Canonical products are permanent identities; offers are temporary
observations. A key is complete only when every identity field is known --
brand, model, RAM, storage, colour, SIM. Anything less is a PartialKey and
must be resolved unambiguously or parked.
"""
from dataclasses import dataclass

from narxnoma.matching.brands import BRAND_LABELS, BRANDS_WITHOUT_PUBLISHED_RAM
from narxnoma.matching.features import Features

SIM_KINDS = ("dual", "esim_only", "unknown")

# Product categories the crawler can sweep. V1 was smartphones only; Plan 5
# (2026-08-10) extends to the other big electronics lines each source sells.
CATEGORIES = (
    "smartphones",
    "televisions",
    "laptops",
    "acs",
    "fridges",
    "washers",
    "ovens",
)

# RU display prefix per category, used by display_name() (crawler UI language
# is Russian; the web layer localises separately).
CATEGORY_PREFIX = {
    "smartphones": "Смартфон",
    "televisions": "Телевизор",
    "laptops": "Ноутбук",
    "acs": "Кондиционер",
    "fridges": "Холодильник",
    "washers": "Стиральная машина",
    "ovens": "Духовой шкаф",
}

# Categories whose identity is NOT the phone signature. Phones key on
# brand+model+RAM+storage+colour+sim; a TV, fridge or oven keys on
# brand+model alone (colour/capacity/usage are not identity).
NON_PHONE_CATEGORIES = frozenset(CATEGORIES) - {"smartphones"}

_COLOR_RU = {
    "black": "Черный", "white": "Белый", "silver": "Серебристый",
    "gray": "Серый", "gold": "Золотой", "blue": "Синий", "red": "Красный",
    "brown": "Коричневый", "green": "Зеленый", "purple": "Фиолетовый",
    "orange": "Оранжевый", "pink": "Розовый", "beige": "Бежевый",
    "burgundy": "Бордовый", "yellow": "Желтый",
}

# Model tokens must be ordered deliberately: model_tokens is a frozenset, so
# alphabetical sorting produces "17 Max Pro", "15 Note Redmi" and "Fe S25".
# Family words, read first. "fold"/"flip" join them for the same reason
# "note" is here: the real name is "Galaxy Z Fold 7", never "Galaxy Z 7 Fold".
_MODEL_PREFIX_ORDER = ["redmi", "note", "fold", "flip"]
_MODEL_SUFFIX_RANK = {
    "pro": 1, "plus": 2, "max": 3, "ultra": 4, "air": 5,
    "fe": 6, "se": 7, "lite": 8, "mini": 9,
}
_UPPERCASE_TOKENS = {"fe", "se"}                  # initialisms, not words


@dataclass(frozen=True)
class VariantKey:
    brand: str
    model_tokens: frozenset[str]
    ram_gb: int | None        # None is legitimate for brands that omit RAM
    storage_gb: int | None    # None outside smartphones (a TV has no storage)
    color: str | None         # None outside smartphones (colour is not identity)
    sim_kind: str | None      # None outside smartphones (no SIM)
    category: str = "smartphones"


@dataclass(frozen=True)
class PartialKey:
    brand: str | None
    model_tokens: frozenset[str]
    ram_gb: int | None
    storage_gb: int | None
    color: str | None
    sim_kind: str
    category: str = "smartphones"


def _check_category(category: str) -> None:
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {CATEGORIES}, got {category!r}")


def variant_key(f: Features, sim_kind: str, category: str = "smartphones") -> VariantKey | None:
    """A complete canonical identity, or None if any identity field is unknown.

    RAM is required only for brands that publish it. Apple does not, and
    extract_memory deliberately refuses to infer it -- so requiring RAM here
    would make every iPhone permanently unkeyable.

    Non-phone categories (TVs, laptops, ACs, fridges, washers, ovens) key on
    brand + model alone; colour, SIM, RAM and storage are NOT identity for
    them (a TV's black bezel doesn't distinguish products, and requiring a
    memory figure would make most appliances unkeyable).
    """
    _check_category(category)
    if not (f.brand and f.model_tokens):
        return None
    if category in NON_PHONE_CATEGORIES:
        return VariantKey(
            brand=f.brand,
            model_tokens=f.model_tokens,
            ram_gb=None,
            storage_gb=f.storage_gb or None,
            color=None,
            sim_kind=None,
            category=category,
        )
    if not f.storage_gb or not f.primary_color:
        return None
    if f.brand not in BRANDS_WITHOUT_PUBLISHED_RAM and not f.ram_gb:
        return None
    if sim_kind not in SIM_KINDS:
        raise ValueError(f"sim_kind must be one of {SIM_KINDS}, got {sim_kind!r}")
    if sim_kind == "unknown":
        sim_kind = "dual"
    return VariantKey(
        brand=f.brand,
        model_tokens=f.model_tokens,
        ram_gb=f.ram_gb,
        storage_gb=f.storage_gb,
        color=f.primary_color,
        sim_kind=sim_kind,
        category=category,
    )


def partial_key(f: Features, sim_kind: str, category: str = "smartphones") -> PartialKey:
    _check_category(category)
    return PartialKey(
        brand=f.brand,
        model_tokens=f.model_tokens,
        ram_gb=f.ram_gb,
        storage_gb=f.storage_gb,
        color=f.primary_color,
        sim_kind=sim_kind,
        category=category,
    )


def _compatible(partial: PartialKey, full: VariantKey) -> bool:
    if partial.brand is not None and partial.brand != full.brand:
        return False
    if partial.model_tokens != full.model_tokens:
        return False
    if partial.ram_gb is not None and partial.ram_gb != full.ram_gb:
        return False
    if partial.storage_gb is not None and partial.storage_gb != full.storage_gb:
        return False
    if partial.color is not None and partial.color != full.color:
        return False
    if partial.sim_kind != "unknown" and partial.sim_kind != full.sim_kind:
        return False
    return True


def resolve_partial(partial: PartialKey, candidates: list[VariantKey]) -> VariantKey | None:
    """Attach only when EXACTLY ONE canonical variant is compatible.

    Zero matches or two-plus matches both return None. Never guess: an
    ambiguous offer belongs in unresolved_offer, not on a product page.
    """
    matches = [c for c in candidates if _compatible(partial, c)]
    return matches[0] if len(matches) == 1 else None


def ordered_model_tokens(tokens: frozenset[str]) -> list[str]:
    """Family prefix, then designators, then modifiers in canonical rank.

    Alphabetical order is wrong: "17 Pro Max" sorts to "17 Max Pro" and
    "Redmi Note 15" to "15 Note Redmi".
    """
    prefixes = [t for t in _MODEL_PREFIX_ORDER if t in tokens]
    suffixes = sorted(
        (t for t in tokens if t in _MODEL_SUFFIX_RANK),
        key=lambda t: _MODEL_SUFFIX_RANK[t],
    )
    used = set(prefixes) | set(suffixes)
    designators = sorted(t for t in tokens if t not in used)
    return prefixes + designators + suffixes


def _token_label(token: str) -> str:
    if token in _UPPERCASE_TOKENS or any(c.isdigit() for c in token):
        return token.upper()
    return token.capitalize()


def display_name(key: VariantKey) -> str:
    """Generated from the key -- never copied from a retailer.

    Copying retailer names is exactly how a competitor ended up with
    "Cosmic orange" and "Cosmic Orange" as two separate products.

    EVERY field of the key must reach the name, or the generator reintroduces
    the confusion it exists to prevent. sim_kind was omitted, so an eSIM-only
    phone and its dual-SIM sibling -- different products, priced differently --
    rendered byte-identical; 42 pairs of live variants were indistinguishable,
    including "Смартфон Apple iPhone 17 Pro 256 ГБ, Оранжевый" twice, at
    16,985,000 and 17,690,000. test_no_two_distinct_keys_share_a_display_name
    states the invariant directly.

    Non-phone categories: "Телевизор Samsung UE55 Неодим" -- colour/SIM are
    absent from the key, and storage only appears when the spec carries one
    (a laptop's 512GB SSD does; a fridge's capacity does not).
    """
    prefix = CATEGORY_PREFIX.get(key.category, key.category.capitalize())
    brand = BRAND_LABELS.get(key.brand, key.brand.capitalize())
    model = " ".join(_token_label(t) for t in ordered_model_tokens(key.model_tokens))
    if key.category in NON_PHONE_CATEGORIES:
        parts = [prefix, brand, model]
        if key.storage_gb:
            parts.append(f"{key.storage_gb} ГБ")
        return " ".join(parts)
    color = _COLOR_RU.get(key.color, key.color.capitalize())
    memory = f"{key.ram_gb}/{key.storage_gb}" if key.ram_gb else str(key.storage_gb)
    sim = " (eSIM)" if key.sim_kind == "esim_only" else ""
    return f"{prefix} {brand} {model} {memory} ГБ, {color}{sim}"


def slug(key: VariantKey) -> str:
    parts = [key.brand, *ordered_model_tokens(key.model_tokens)]
    if key.ram_gb:
        parts.append(str(key.ram_gb))
    if key.storage_gb:
        parts.append(str(key.storage_gb))
    if key.color:
        parts.append(key.color)
    if key.sim_kind == "esim_only":
        parts.append("esim")
    # Non-phone slugs are category-prefixed so a TV and a laptop can never
    # claim the same URL. Phone slugs are left unchanged for DB compatibility
    # (the existing ~1,400 rows key on the current format).
    if key.category in NON_PHONE_CATEGORIES:
        parts.insert(0, key.category)
    return "-".join(parts)
