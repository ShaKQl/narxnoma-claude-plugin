"""Live contract tests: hit the real retailer APIs once and check the shape
we depend on hasn't silently changed.

Skipped by default (see `addopts = "-m 'not live'"` in pyproject.toml). Run
explicitly with:

    python -m pytest tests/sources/test_contract_live.py -m live -v
"""
import pytest

from narxnoma.sources.base import PRICE_MAX, PRICE_MIN
from narxnoma.sources.olcha import API_URL, CATEGORY, OlchaSource, PER_PAGE, parse
from narxnoma.sources.http import get_json


@pytest.mark.live
def test_olcha_catalogue_page_still_matches_documented_shape():
    source = OlchaSource()
    session = source._get_session()
    payload = get_json(
        session, API_URL, params={"page": 1, "per_page": PER_PAGE, "category": CATEGORY},
    )

    data = payload.get("data")
    assert data is not None, "top-level 'data' key is gone"
    assert "products" in data, "'data.products' is gone"
    assert "paginator" in data, "'data.paginator' is gone"
    assert "last_page" in data["paginator"], "'data.paginator.last_page' is gone"

    products = data["products"]
    assert products, "live catalogue page returned no products"
    first = products[0]
    for field in ("name_ru", "alias", "discount_price", "quantity"):
        assert field in first, f"documented field {field!r} is missing from a live product"

    listings = parse(payload)
    assert listings, "parse() found nothing in a live response"
    for lst in listings:
        assert lst.store_slug == "olcha"
        assert PRICE_MIN <= lst.price <= PRICE_MAX
        assert lst.url.startswith("https://olcha.uz/ru/product/view/")
