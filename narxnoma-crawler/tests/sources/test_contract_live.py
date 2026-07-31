"""Live contract tests: hit the real retailer APIs once and check the shape
we depend on hasn't silently changed.

Skipped by default (see `addopts = "-m 'not live'"` in pyproject.toml). Run
explicitly with:

    python -m pytest tests/sources/test_contract_live.py -m live -v
"""
import pytest

from narxnoma.sources.alifshop import (
    API_URL as ALIFSHOP_API_URL,
    SIZE as ALIFSHOP_SIZE,
    AlifshopSource,
    parse as alifshop_parse,
)
from narxnoma.sources.base import PRICE_MAX, PRICE_MIN
from narxnoma.sources.beemarket import (
    API_URL as BEEMARKET_API_URL,
    PHONE_CATEGORY_SLUGS as BEEMARKET_PHONE_CATEGORY_SLUGS,
    SWEEP_API_URL as BEEMARKET_SWEEP_API_URL,
    BeemarketSource,
    _filter_phone_listings as beemarket_filter_phone_listings,
    parse as beemarket_parse,
)
from narxnoma.sources.idea import (
    API_URL as IDEA_API_URL,
    BRAND_QUERIES as IDEA_BRAND_QUERIES,
    QUANTITY as IDEA_QUANTITY,
    IdeaSource,
    parse as idea_parse,
)
from narxnoma.sources.olcha import API_URL, CATEGORY, OlchaSource, PER_PAGE, parse
from narxnoma.sources.texnomart import (
    API_URL as TEXNOMART_API_URL,
    LIMIT as TEXNOMART_LIMIT,
    SWEEP_QUERY as TEXNOMART_SWEEP_QUERY,
    TexnomartSource,
    parse as texnomart_parse,
)
from narxnoma.sources.http import get_json, post_json


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


@pytest.mark.live
def test_texnomart_search_page_still_matches_documented_shape():
    source = TexnomartSource()
    session = source._get_session()
    payload = get_json(
        session,
        TEXNOMART_API_URL,
        params={"q": TEXNOMART_SWEEP_QUERY, "page": 1, "limit": TEXNOMART_LIMIT},
    )

    data = payload.get("data")
    assert data is not None, "top-level 'data' key is gone"
    assert "products" in data, "'data.products' is gone"
    assert "pagination" in data, "'data.pagination' is gone"
    assert "total_page" in data["pagination"], "'data.pagination.total_page' is gone"

    products = data["products"]
    assert products, "live search page returned no products"
    first = products[0]
    for field in ("id", "name", "sale_price", "old_price"):
        assert field in first, f"documented field {field!r} is missing from a live product"

    listings = texnomart_parse(payload)
    assert listings, "parse() found nothing in a live response"
    for lst in listings:
        assert lst.store_slug == "texnomart"
        assert PRICE_MIN <= lst.price <= PRICE_MAX
        assert lst.url.startswith("https://texnomart.uz/product/detail/")
        assert lst.url.endswith("/")


@pytest.mark.live
def test_idea_search_still_matches_documented_shape():
    source = IdeaSource()
    session = source._get_session()
    payload = get_json(
        session,
        IDEA_API_URL,
        params={"search": IDEA_BRAND_QUERIES[0], "quantity": IDEA_QUANTITY,
                "type[]": ["shops", "products"]},
    )

    assert "products" in payload, "'products' is gone"

    products = payload["products"]
    assert products, "live search returned no products"
    first = products[0]
    for field in ("id", "name", "url", "current_price"):
        assert field in first, f"documented field {field!r} is missing from a live product"

    listings = idea_parse(payload)
    assert listings, "parse() found nothing in a live response"
    for lst in listings:
        assert lst.store_slug == "idea"
        assert PRICE_MIN <= lst.price <= PRICE_MAX
        assert lst.url.startswith("https://idea.uz/")


@pytest.mark.live
def test_beemarket_category_sweep_still_matches_documented_shape():
    """Checks the narrowed, undocumented endpoint sweep() actually calls
    (see beemarket.py module docstring for why it isn't the generic search
    the task brief documents) still returns the doubly-nested envelope and
    documented fields, still scopes to smartfony server-side, and that
    prices still land inside the fences.
    """
    source = BeemarketSource()
    session = source._get_session()
    payload = get_json(
        session, BEEMARKET_SWEEP_API_URL, params={"page": 1, "is_bshop": 1},
    )

    data = payload.get("data")
    assert data is not None, "top-level 'data' key is gone"
    assert "data" in data, "'data.data' is gone"
    assert "last_page" in data, "'data.last_page' is gone"

    products = data["data"]
    assert products, "live category sweep returned no products"
    first = products[0]
    for field in ("id", "name", "slug", "category", "actual_price", "price"):
        assert field in first, f"documented field {field!r} is missing from a live product"
    assert first["category"]["slug"] == "smartfony", (
        "the category-scoped endpoint no longer scopes to smartfony -- "
        "sweep() would silently start pulling the whole catalogue again"
    )

    listings = beemarket_parse(payload)
    assert listings, "parse() found nothing in a live response"
    filtered = beemarket_filter_phone_listings(listings)
    assert len(filtered) == len(listings), (
        "the category endpoint returned a non-phone category live -- "
        "PHONE_CATEGORY_SLUGS or the endpoint's scoping has drifted"
    )
    for lst in filtered:
        assert lst.store_slug == "beemarket"
        assert PRICE_MIN <= lst.price <= PRICE_MAX
        assert lst.url.startswith("https://market.beeline.uz/")
        assert lst.raw.get("category", {}).get("slug") in BEEMARKET_PHONE_CATEGORY_SLUGS


@pytest.mark.live
def test_beemarket_search_still_matches_documented_shape():
    """The documented generic search endpoint, used by search(query)."""
    source = BeemarketSource()
    session = source._get_session()
    payload = get_json(
        session,
        BEEMARKET_API_URL,
        params={"q": "Honor", "is_bshop": 1, "page": 1},
    )

    data = payload.get("data")
    assert data is not None, "top-level 'data' key is gone"
    assert "data" in data, "'data.data' is gone"
    assert "last_page" in data, "'data.last_page' is gone"

    products = data["data"]
    assert products, "live search returned no products"
    first = products[0]
    for field in ("id", "name", "slug", "category", "actual_price", "price"):
        assert field in first, f"documented field {field!r} is missing from a live product"

    listings = beemarket_parse(payload)
    assert listings, "parse() found nothing in a live response"
    for lst in listings:
        assert lst.store_slug == "beemarket"
        assert PRICE_MIN <= lst.price <= PRICE_MAX
        assert lst.url.startswith("https://market.beeline.uz/")


@pytest.mark.live
def test_alifshop_search_still_matches_documented_shape():
    """Checks the documented fields, the 0-based page contract, and --
    above all -- that the tiyin-to-SUM conversion still lands prices inside
    the fences against a live response, not just the recorded fixture.
    """
    source = AlifshopSource()
    session = source._get_session()
    payload = post_json(
        session,
        ALIFSHOP_API_URL,
        json={"query": "Samsung", "page": 0, "size": ALIFSHOP_SIZE},
    )

    assert "items" in payload, "'items' is gone"
    assert "n_pages" in payload, "'n_pages' is gone"

    items = payload["items"]
    assert items, "live search returned no items"
    first = items[0]
    for field in ("id", "slug", "price", "product", "partner"):
        assert field in first, f"documented field {field!r} is missing from a live item"
    assert "name" in first["product"], "'product.name' is gone"
    assert "slug" in first["partner"], "'partner.slug' is gone"

    listings = alifshop_parse(payload)
    assert listings, "parse() found nothing in a live response"
    for lst in listings:
        assert lst.store_slug == "alifshop"
        assert PRICE_MIN <= lst.price <= PRICE_MAX
        assert lst.url.startswith("https://alifshop.uz/moderated-offer/")
