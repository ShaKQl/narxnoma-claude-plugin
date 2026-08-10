"""Texnomart category-aware sweep (Plan 5): query + allow-list mapping."""
from narxnoma.sources.base import Listing
from narxnoma.sources.texnomart import CATEGORY_KEEP_WORD, CATEGORY_QUERY, TexnomartSource


def test_category_maps_cover_all_supported_categories():
    # texnomart names its results in Uzbek (Latin): Televizori, Noutbuki,
    # Konditsioneri, Muzlatgichi, "Kir yuvish mashinasi", Duxovkasi.
    assert CATEGORY_QUERY == {
        "smartphones": "smartfon",
        "televisions": "televizor",
        "laptops": "noutbuk",
        "acs": "konditsioner",
        "fridges": "xolodilnik",
        "washers": "stiraln",
        "ovens": "duxovka",
    }
    assert CATEGORY_KEEP_WORD["televisions"] == "televizor"
    assert CATEGORY_KEEP_WORD["fridges"] == "muzlatgich"  # Uzbek, not Russian
    assert CATEGORY_KEEP_WORD["washers"] == "kir yuvish"


def test_sweep_allow_lists_by_category_word_and_tags():
    src = TexnomartSource()
    src._paginate = lambda q: [
        Listing(store_slug="texnomart", source_key="1", name_raw="Televizor Premier 43PRM700S",
                price=4_000_000, url="https://texnomart.uz/x", category="smartphones"),
        Listing(store_slug="texnomart", source_key="2", name_raw="Samsung Galaxy A26",
                price=3_000_000, url="https://texnomart.uz/x", category="smartphones"),
    ]
    out = list(src.sweep(category="televisions"))
    assert [l.source_key for l in out] == ["1"]
    assert out[0].category == "televisions"


def test_sweep_rejects_unknown_category():
    src = TexnomartSource()
    try:
        list(src.sweep(category="toasters"))
        assert False, "expected ValueError"
    except ValueError:
        pass