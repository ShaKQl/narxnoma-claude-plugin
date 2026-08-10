"""Alifshop category-aware sweep (Plan 5): bucket-keyword mapping + discovery."""
from narxnoma.sources.alifshop import CATEGORY_BUCKET_KEYWORD, category_from_aggregations


def test_category_bucket_keywords_cover_all_supported_categories():
    # Verified live 2026-08-10 via the search facet aggregation.
    assert CATEGORY_BUCKET_KEYWORD == {
        "smartphones": "смартфон",
        "televisions": "телевизор",
        "laptops": "ноутбук",
        "acs": "кондиционер",
        "fridges": "холодильник",
        "washers": "стиральн",
        "ovens": "духов",
    }


def test_discovers_the_largest_matching_bucket():
    payload = {
        "aggregations": {
            "category": {
                "terms": [
                    {"key": "Телевизоры", "doc_count": 542},
                    {"key": "Смарт телевизоры", "doc_count": 27},
                    {"key": "Смартфоны Samsung", "doc_count": 100},
                ]
            }
        }
    }
    assert category_from_aggregations(payload, "телевизор") == "Телевизоры"


def test_no_match_returns_none():
    assert category_from_aggregations({}, "телевизор") is None