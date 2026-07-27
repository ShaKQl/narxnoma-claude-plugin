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
    for target in BRAND_ALIASES.values():
        assert target in BRANDS


def test_every_brand_has_a_label():
    for b in BRANDS:
        assert canonical_brand(b) in BRAND_LABELS
