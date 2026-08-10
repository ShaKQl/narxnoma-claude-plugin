"""Category-aware identity (Plan 5): non-phone products key on
brand + model alone; phones keep the full colour/SIM/memory signature.
"""
import pytest

from narxnoma.matching.features import extract_features
from narxnoma.matching.keys import (
    CATEGORY_PREFIX,
    NON_PHONE_CATEGORIES,
    display_name,
    slug,
    variant_key,
)


def _tv_key():
    return variant_key(extract_features("Телевизор Samsung UE55 55\" Black"), "dual", "televisions")


def test_non_phone_keys_on_brand_and_model_alone():
    # A TV's colour and diagonal are not identity: two titles that differ only
    # in colour/capacity must produce the SAME key (one product, many offers).
    k1 = variant_key(extract_features("Телевизор Samsung UE55 55\" Black"), "dual", "televisions")
    k2 = variant_key(extract_features("Телевизор Samsung UE55 55\" Silver"), "dual", "televisions")
    assert k1 is not None and k2 is not None
    assert k1 == k2
    assert k1.color is None and k1.sim_kind is None
    assert k1.category == "televisions"


def test_non_phone_does_not_require_ram_or_storage():
    # A fridge has no RAM and no storage; it must still be keyable.
    k = variant_key(
        extract_features("Холодильник Samsung RB34T 300 лт"), "dual", "fridges"
    )
    assert k is not None
    assert k.ram_gb is None and k.storage_gb is None


def test_non_phone_requires_brand_and_model():
    assert variant_key(extract_features("Телевизор 55\" 4K"), "dual", "televisions") is None


def test_all_non_phone_categories_have_a_display_prefix():
    assert set(CATEGORY_PREFIX) == NON_PHONE_CATEGORIES | {"smartphones"}
    for c in NON_PHONE_CATEGORIES:
        assert CATEGORY_PREFIX[c]


def test_non_phone_display_name_and_slug():
    k = _tv_key()
    assert k is not None
    assert display_name(k).startswith("Телевизор")
    assert slug(k).startswith("televisions-")


def test_phone_key_and_slug_unchanged():
    k = variant_key(extract_features("Смартфон Honor X9D 12/256 ГБ, Черный"), "dual")
    assert k is not None
    assert k.category == "smartphones"
    assert display_name(k) == "Смартфон Honor X9D 12/256 ГБ, Черный"
    assert slug(k) == "honor-x9d-12-256-black"


def test_invalid_category_rejected():
    with pytest.raises(ValueError):
        variant_key(extract_features("X Y"), "dual", "toasters")