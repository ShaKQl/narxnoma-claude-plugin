"""Category flows from an offer row through identification (Plan 5)."""
from narxnoma.pipeline.extract import identify


def test_identify_uses_offer_category_for_non_phone():
    idn = identify(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "name_raw": 'Телевизор Samsung UE55 55" Black',
            "category": "televisions",
        }
    )
    assert idn.key is not None
    assert idn.key.category == "televisions"
    assert idn.key.color is None and idn.key.sim_kind is None


def test_identify_defaults_to_smartphones():
    # Offers written before the category column existed carry no category.
    idn = identify(
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "name_raw": "Смартфон Honor X9D 12/256 ГБ, Черный",
        }
    )
    assert idn.key is not None
    assert idn.key.category == "smartphones"
    assert idn.key.color == "black"