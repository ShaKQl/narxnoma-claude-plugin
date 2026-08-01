"""Tests for the shared brand-query vocabulary used by idea.py and
alifshop.py -- both sources have no browsable catalogue, so this list *is*
their entire reach into the retailer's stock; a brand silently missing
here is permanently invisible to both sweeps.
"""
from narxnoma.matching.brands import BRAND_ALIASES, BRANDS
from narxnoma.sources.brand_queries import BRAND_QUERIES


def test_brand_queries_covers_major_brands():
    lowered = {q.lower() for q in BRAND_QUERIES}
    for brand in ("oppo", "huawei", "vivo"):
        assert brand in lowered
    assert "redmi" in lowered, "alias keys must be queried, not just canonical brands"


def test_brand_queries_is_derived_from_the_canonical_vocabulary_not_hardcoded():
    # Every canonical brand and every alias key must be queried, and nothing
    # else -- this must track narxnoma.matching.brands exactly, never drift.
    assert set(BRAND_QUERIES) == set(BRANDS) | set(BRAND_ALIASES)
    assert list(BRAND_QUERIES) == sorted(BRAND_QUERIES)
    assert isinstance(BRAND_QUERIES, tuple)
