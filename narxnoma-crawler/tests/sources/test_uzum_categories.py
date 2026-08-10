"""Uzum category-aware parse/sweep (Plan 5): id mapping + tagging."""
from narxnoma.sources.base import Listing
from narxnoma.sources.uzum import CATEGORY_IDS, parse


def test_category_ids_cover_all_supported_categories():
    # Verified live 2026-08-10 via makeSearch per product type, then RE-verified
    # the same day while fixing the category crawl frontier. Two ids were
    # missing, both confirmed by reading catalogCard.category off a live
    # response:
    #   13 Газовые плиты  -- "газовая плита" returns 72/72 under id 13, not 11,
    #      so every gas cooker uzum sells was fetched and then filtered out.
    #   83 Морозильники   -- the Uzbek "muzlatgich" resolves to FREEZERS here
    #      ("холодильник"/"sovutgich" reach id 82), and freezers belong with
    #      fridges for the same reason cookers belong with ovens.
    assert CATEGORY_IDS == {
        "smartphones": {15271, 15272},
        "televisions": {12601},
        "laptops": {12520},
        "acs": {14373},
        "fridges": {82, 83},
        "washers": {15291, 15296},
        "ovens": {11, 13},
    }


def _payload_with(category_id):
    return {
        "data": {
            "makeSearch": {
                "items": [
                    {
                        "catalogCard": {
                            "category": {"id": category_id, "title": "X"},
                            "productId": 1,
                            "title": "Телевизор Samsung",
                            "skuList": [
                                {"id": 10, "sellPrice": 4000000, "fullPrice": 5000000,
                                 "availableAmount": 1, "characteristicValues": []}
                            ],
                        }
                    }
                ]
            }
        }
    }


def test_parse_filters_and_tags_by_category():
    out = parse(_payload_with(12601), category="televisions")
    assert len(out) == 1 and out[0].category == "televisions"
    # A smartphone in the same payload is dropped for the televisions sweep.
    assert len(parse(_payload_with(15271), category="televisions")) == 0


def test_parse_defaults_to_smartphones():
    out = parse(_payload_with(15271))
    assert len(out) == 1 and out[0].category == "smartphones"


def test_parse_rejects_unknown_category():
    try:
        parse(_payload_with(1), category="toasters")
        assert False, "expected ValueError"
    except ValueError:
        pass