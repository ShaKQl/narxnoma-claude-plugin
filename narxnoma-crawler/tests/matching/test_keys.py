from dataclasses import replace

from narxnoma.matching import VariantKey
from narxnoma.matching.features import extract_features as F
from narxnoma.matching.keys import (
    display_name, partial_key, resolve_partial, slug, variant_key,
)


def k(name, sim_kind="dual"):
    return variant_key(F(name), sim_kind)


def test_full_key_from_complete_listing():
    key = k("Смартфон Honor X9d 12/256 ГБ, черный")
    assert key.brand == "honor"
    assert key.ram_gb == 12 and key.storage_gb == 256
    assert key.color == "black"
    assert key.sim_kind == "dual"


def test_key_is_none_when_identity_incomplete():
    # No storage at all -> cannot be a canonical variant.
    assert variant_key(F("Чехол для Honor X9d"), "dual") is None
    # No colour -> colour is a hard identity field.
    assert variant_key(F("Honor X9d 12/256 GB"), "dual") is None


def test_apple_key_is_complete_without_ram():
    # Apple never publishes RAM and extract_memory refuses to infer it.
    # If RAM were required, NO iPhone could ever be keyed.
    key = k("Смартфон Apple iPhone 17 Pro Max 256 ГБ, Silver")
    assert key is not None
    assert key.ram_gb is None
    assert key.storage_gb == 256


def test_non_apple_key_still_requires_ram():
    assert variant_key(F("Samsung Galaxy A17 128GB Blue"), "dual") is None


def test_equal_keys_for_differently_worded_same_phone():
    a = k("Смартфон Honor X9d 12/256 ГБ, черный")
    b = k("Honor X9d 12/256 GB Midnight Black")
    assert a == b
    assert hash(a) == hash(b)


def test_case_and_punctuation_do_not_create_duplicates():
    # uzprice has "Cosmic orange" and "Cosmic Orange" as two products.
    a = k("Смартфон Apple iPhone 17 Pro Max 256 ГБ, Cosmic orange")
    b = k("Смартфон Apple iPhone 17 Pro Max 256 ГБ, Cosmic Orange")
    assert a == b


def test_esim_only_is_a_different_variant():
    dual = k("Смартфон Apple iPhone 17 Pro Max 256 ГБ, Silver", "dual")
    esim = k("Смартфон Apple iPhone 17 Pro Max 256 ГБ, Silver", "esim_only")
    assert dual != esim


def test_partial_key_resolves_when_exactly_one_candidate_matches():
    full = [k("Redmi Note 15 8/256 ГБ, черный")]
    p = partial_key(F("Redmi Note 15 256GB Black"), "dual")
    assert p.ram_gb is None
    assert resolve_partial(p, full) == full[0]


def test_partial_key_REFUSES_when_ambiguous():
    # THE RULE: both 8/256 and 12/256 exist, so a listing with no RAM is
    # genuinely ambiguous. uzprice attaches it anyway and lets it set the
    # headline price. We refuse.
    full = [
        k("Redmi Note 15 8/256 ГБ, черный"),
        k("Redmi Note 15 12/256 ГБ, черный"),
    ]
    p = partial_key(F("Redmi Note 15 256GB Black"), "dual")
    assert resolve_partial(p, full) is None


def test_partial_key_refuses_when_nothing_matches():
    full = [k("Redmi Note 15 8/256 ГБ, черный")]
    p = partial_key(F("Galaxy A17 128GB Blue"), "dual")
    assert resolve_partial(p, full) is None


def test_display_name_is_generated_not_copied():
    key = k("HONOR   x9d 12/256gb   midnight black")
    assert display_name(key) == "Смартфон Honor X9D 12/256 ГБ, Черный"


def test_display_name_orders_modifiers_not_alphabetically():
    # sorted() would give "17 Max Pro". Pro precedes Max in every real name.
    key = k("Смартфон Apple iPhone 17 Pro Max 256 ГБ, Silver")
    assert display_name(key) == "Смартфон Apple iPhone 17 Pro Max 256 ГБ, Серебристый"


def test_display_name_puts_family_prefix_first():
    # sorted() would give "15 Note Redmi".
    key = k("Смартфон Xiaomi Redmi Note 15 8/256 ГБ, чёрный")
    assert display_name(key) == "Смартфон Xiaomi Redmi Note 15 8/256 ГБ, Черный"


def test_display_name_uppercases_initialisms():
    # sorted() would give "Fe S25".
    key = k("Samsung Galaxy S25 FE 8/128 Navy")
    assert display_name(key) == "Смартфон Samsung S25 FE 8/128 ГБ, Синий"


def test_slug_is_deterministic_and_url_safe():
    a = k("Смартфон Honor X9d 12/256 ГБ, черный")
    b = k("Honor X9d 12/256 GB Midnight Black")
    assert slug(a) == slug(b)
    assert slug(a) == "honor-x9d-12-256-black"


def test_slug_omits_ram_when_the_brand_has_none():
    assert slug(k("Смартфон Apple iPhone 17 Pro Max 256 ГБ, Silver")) == \
        "apple-17-pro-max-256-silver"


def test_esim_only_slug_is_distinct():
    dual = slug(k("Смартфон Apple iPhone 17 Pro 256 ГБ, Silver", "dual"))
    esim = slug(k("Смартфон Apple iPhone 17 Pro 256 ГБ, Silver", "esim_only"))
    assert dual != esim
    assert esim.endswith("-esim")


def test_fold_and_flip_are_different_products():
    # THE MERGE: "fold"/"flip" were neither digit-bearing nor in
    # MODEL_MODIFIERS, so both names reduced to model_tokens={'7'} and
    # collapsed onto the identical key samsung-7-12-256-black, scoring 60
    # with why() == "OK". A Fold costs roughly twice a Flip.
    fold = k("Samsung Galaxy Z Fold 7 Black 12/256")
    flip = k("Samsung Galaxy Z Flip 7 Black 12/256")
    assert fold is not None and flip is not None
    assert fold != flip
    assert slug(fold) != slug(flip)


def test_unknown_sim_normalises_to_dual():
    # slug() was not injective: sim_kind "unknown" and "dual" built different
    # VariantKeys but identical slugs, so two keys claimed one URL.
    # uzum.md §6 documents eSIM-only variants as ALWAYS explicitly marked (in
    # three encodings), so an unmarked phone is the ordinary dual-SIM one.
    f = F("Смартфон Apple iPhone 17 Pro Max 256 ГБ, Silver")
    assert variant_key(f, "unknown") == variant_key(f, "dual")
    assert variant_key(f, "unknown").sim_kind == "dual"
    # esim_only stays distinct, and keeps its slug suffix.
    assert variant_key(f, "esim_only") != variant_key(f, "dual")
    assert slug(variant_key(f, "esim_only")).endswith("-esim")


def test_invalid_sim_kind_is_rejected():
    # SIM_KINDS was declared but never enforced, so any string became part of
    # a canonical identity -- a typo ("Dual", "dual_sim") would silently mint
    # a second canonical product for a phone that already had one.
    f = F("Смартфон Honor X9d 12/256 ГБ, черный")
    for bad in ["Dual", "dual_sim", "", "esim"]:
        try:
            variant_key(f, bad)
        except ValueError:
            continue
        raise AssertionError(f"variant_key accepted invalid sim_kind {bad!r}")


def test_display_name_distinguishes_an_esim_only_variant():
    """sim_kind is part of the key, so it must be part of the NAME.

    slug() appends "esim" and display_name() did not, so an eSIM-only phone
    and its dual-SIM sibling -- genuinely different products at genuinely
    different prices -- rendered byte-identical. Live, that produced 42 pairs
    of variants a user could not tell apart, including
    'Смартфон Apple iPhone 17 Pro 256 ГБ, Оранжевый' twice at 16,985,000 and
    17,690,000.

    Generated names are supposed to make duplicates structurally impossible;
    a generator that drops a key field reintroduces exactly the confusion it
    exists to prevent.
    """
    dual = VariantKey(brand="apple", model_tokens=frozenset({"17", "pro"}),
                      ram_gb=None, storage_gb=256, color="orange", sim_kind="dual")
    esim = replace(dual, sim_kind="esim_only")

    assert display_name(dual) == "Смартфон Apple iPhone 17 Pro 256 ГБ, Оранжевый"
    assert display_name(esim) != display_name(dual)
    assert "eSIM" in display_name(esim)


def test_no_two_distinct_keys_share_a_display_name():
    """The invariant behind the test above, stated directly: if two keys
    differ at all, their generated names must differ too.
    """
    base = VariantKey(brand="apple", model_tokens=frozenset({"17", "pro"}),
                      ram_gb=None, storage_gb=256, color="orange", sim_kind="dual")
    variations = [
        base,
        replace(base, sim_kind="esim_only"),
        replace(base, storage_gb=512),
        replace(base, color="blue"),
        replace(base, model_tokens=frozenset({"17", "pro", "max"})),
        replace(base, ram_gb=12),
    ]
    names = [display_name(k) for k in variations]
    assert len(set(names)) == len(names), f"collision among {names}"
