"""The crawl frontier per category.

A frontier entry missing here is not a degraded name -- it is zero offers,
permanently, from every source with no browsable catalogue, and nothing in the
system reports the absence of something never looked for.
"""
import pytest

from narxnoma.matching.keys import CATEGORIES
from narxnoma.sources.brand_queries import (
    BRAND_QUERIES,
    CATEGORY_QUERIES,
    queries_for,
)


def test_every_category_has_a_frontier():
    # A category the crawler sweeps but has no queries for would sweep nothing
    # while reporting success.
    for category in CATEGORIES:
        assert queries_for(category), category


def test_phones_keep_the_brand_frontier():
    assert queries_for("smartphones") == BRAND_QUERIES


@pytest.mark.parametrize("category", sorted(CATEGORY_QUERIES))
def test_non_phone_frontiers_lead_with_the_product_noun(category):
    # Measured live on uzum: "konditsioner" returns 72 of 72 in-category while
    # the brand query "artel" returns remote controls, vacuum-cleaner filters
    # and electric kettles. The noun does the work; brands are a supplement.
    first = queries_for(category)[0]
    assert first not in BRAND_QUERIES, (
        f"{category} frontier leads with the brand {first!r}"
    )


def test_white_goods_brands_are_reachable_at_all():
    # These sell no phones, so BRAND_QUERIES never contained them -- which is
    # why uzum held zero air conditioners, fridges, washers and ovens.
    for brand in ("artel", "premier", "shivaki", "lg"):
        assert brand not in BRAND_QUERIES
        assert any(brand in queries_for(c) for c in ("fridges", "washers", "acs"))


def test_fridge_frontier_does_not_lead_with_the_freezer_word():
    # "muzlatgich" resolves to FREEZERS on uzum (verified live), so leading
    # with it would sweep the wrong category. It stays in the frontier because
    # other retailers do use it for a refrigerator.
    frontier = queries_for("fridges")
    assert frontier.index("холодильник") < frontier.index("muzlatgich")


def test_an_unswept_category_raises_rather_than_returning_nothing():
    # Returning () would let a caller record a perfectly successful harvest of
    # zero listings -- the failure mode the Source protocol exists to prevent.
    with pytest.raises(ValueError):
        queries_for("toasters")
