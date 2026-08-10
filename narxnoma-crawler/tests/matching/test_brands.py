from narxnoma.matching.brands import (
    BRAND_ALIASES, BRAND_LABELS, BRANDS, BRANDS_WITHOUT_PUBLISHED_RAM, canonical_brand,
)


def test_aliases_collapse_sub_brands():
    assert canonical_brand("iphone") == "apple"
    assert canonical_brand("redmi") == "xiaomi"
    assert canonical_brand("poco") == "xiaomi"


def test_unaliased_brand_passes_through():
    assert canonical_brand("samsung") == "samsung"
    assert canonical_brand("honor") == "honor"


def test_apple_publishes_no_ram():
    # Apple never states RAM in consumer names. This drives both the
    # phantom-RAM guard (Task 4) and key completeness (Task 7).
    assert "apple" in BRANDS_WITHOUT_PUBLISHED_RAM
    assert "samsung" not in BRANDS_WITHOUT_PUBLISHED_RAM


def test_apple_label_includes_iphone():
    # "iphone" is a NON_MODEL_TOKEN, so it never survives into model_tokens.
    # Without it in the label, display names read "Смартфон Apple 17 Pro Max".
    assert BRAND_LABELS["apple"] == "Apple iPhone"
    assert BRAND_LABELS["samsung"] == "Samsung"


def test_every_alias_target_is_a_known_brand():
    # An alias resolving to a brand no vocabulary contains is a silent dead
    # end: the token matches, canonical_brand rewrites it, and the result
    # keys nothing. APPLIANCE_BRANDS is a second recognition vocabulary --
    # kept out of BRANDS because BRANDS doubles as the PHONE crawl frontier --
    # so a target may legitimately live in either.
    from narxnoma.matching.brands import APPLIANCE_BRANDS

    from narxnoma.matching.brands import NON_PHONE_ALIASES

    known = set(BRANDS) | set(APPLIANCE_BRANDS)
    for target in {**BRAND_ALIASES, **NON_PHONE_ALIASES}.values():
        assert target in known, target


def test_every_brand_has_a_label():
    for b in BRANDS:
        assert canonical_brand(b) in BRAND_LABELS


def test_every_appliance_brand_has_a_label():
    # display_name renders brand_label(); a brand without one falls back to
    # .capitalize(), which turns "7tech" into "7Tech" by luck and "aux" into
    # "Aux" wrongly. Every entry is spelled deliberately.
    from narxnoma.matching.brands import APPLIANCE_BRAND_LABELS, APPLIANCE_BRANDS

    missing = [b for b in APPLIANCE_BRANDS if b not in APPLIANCE_BRAND_LABELS]
    assert not missing, f"appliance brands with no display label: {missing}"


def test_new_brands_are_recognised_in_real_listing_shapes():
    from narxnoma.matching import extract_features
    assert extract_features("itel A70 4/128 GB Black").brand == "itel"
    assert extract_features("Nokia 110 4G Dual SIM Blue").brand == "nokia"
    assert extract_features("OnePlus Nord 4 12/256 Green").brand == "oneplus"


# --------------------------------------------------------------------------
# The appliance-only alias map. Separate from BRAND_ALIASES because that dict
# is probed first in the phone path's SUBSTRING scan and also feeds the phone
# crawl frontier -- see brands.py.
# --------------------------------------------------------------------------

def test_appliance_aliases_do_not_leak_into_the_phone_path():
    """The one property that makes a second alias map worth having.

    An appliance alias in BRAND_ALIASES would be probed as a substring against
    every phone name (14,860 golden rows pin that scan) AND would spend a real
    query per cycle at three retailers, asking for a phone brand that does not
    exist.
    """
    from narxnoma.matching.brands import APPLIANCE_BRAND_ALIASES
    from narxnoma.sources.brand_queries import BRAND_QUERIES

    for alias in APPLIANCE_BRAND_ALIASES:
        assert alias not in BRAND_ALIASES, alias
        assert alias not in BRAND_QUERIES, alias
        assert canonical_brand(alias) == alias, f"{alias} resolved on the phone path"


def test_appliance_aliases_resolve_outside_smartphones():
    from narxnoma.matching.brands import canonical_non_phone_brand

    assert canonical_non_phone_brand("prm") == "premier"
    assert canonical_non_phone_brand("shiv") == "shivaki"
    assert canonical_non_phone_brand("zifler") == "ziffler"
    assert canonical_non_phone_brand("бирюса") == "biryusa"
    assert canonical_non_phone_brand("können") == "konnen"
    # The phone aliases still apply outside phones: a MacBook is an Apple.
    assert canonical_non_phone_brand("macbook") == "apple"
    assert canonical_non_phone_brand("bosch") == "bosch"


def test_the_cyrillic_spelling_of_biryusa_keys_the_same_product():
    """The bug the third brand pass found.

    "biryusa" was in the vocabulary in the LATIN spelling and its display
    label was already "Бирюса" -- but every listing writes it in Cyrillic, and
    normalize() correctly leaves an all-Cyrillic token alone. The two
    spellings never met, and 20 offers were unkeyable.
    """
    from narxnoma.matching import extract_features

    cyrillic = extract_features("Холодильник Бирюса M6133", category="fridges")
    assert cyrillic.brand == "biryusa"
    assert cyrillic.model_tokens


def test_third_pass_brands_are_recognised_in_real_listing_shapes():
    from narxnoma.matching import extract_features

    for name, category, brand in (
        ("Кондиционер Gree Clivia Inverter 24 Gold", "acs", "gree"),
        ("Холодильник-морозильник ATLANT ХМ-4621-109-ND", "fridges", "atlant"),
        ("Ноутбук CHUWI GemiBook XPro 8GB", "laptops", "chuwi"),
        ("Телевизор KÖNNEN KN100HS", "televisions", "konnen"),
        ("Konnen KN-BFNF317/SI Sovutgichi", "fridges", "konnen"),
        ("Комбинированная плита Magna FS-M604BB(I)", "ovens", "magna"),
        ("Стиральная машина SHIV-WM 1106 Sentaku - (6 кг) Серый", "washers", "shivaki"),
        ("PRM-350TFNFID/DI", "fridges", "premier"),
        ("Газовые плиты Zifler Breeze Series BGS-6031BE", "ovens", "ziffler"),
    ):
        assert extract_features(name, category=category).brand == brand, name


def test_magna_does_not_swallow_premiers_magnate_line():
    """"Кондиционер Premier PRM-12MGSPA-INV/W Magnate" is a Premier, not a
    Magna. The non-phone probe's word boundary is what keeps them apart -- a
    substring scan would read "magna" inside "Magnate"."""
    from narxnoma.matching import extract_features

    f = extract_features(
        "Кондиционер Premier PRM-12MGSPA-INV/W Magnate GMCC DC inverter", category="acs")
    assert f.brand == "premier"


def test_rivacase_stays_unrecognised_on_purpose():
    """Its listings are laptop BAGS. Leaving the brand out of the vocabulary
    is what keeps them from forming laptop variants."""
    from narxnoma.matching import extract_features

    f = extract_features("Rivacase 7531 Black Eco 15.6 Noutbuk sumkasi", category="laptops")
    assert f.brand is None
