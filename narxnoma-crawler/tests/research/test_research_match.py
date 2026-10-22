from narxnoma.research.match import (
    NON_PHONE_ACCEPT,
    accept_threshold,
    index_by_brand,
    match_target,
    name_delta,
)
from narxnoma.research.model import Target


def L(name, price, key=None, url=None):
    return {
        "store_slug": "x",
        "source_key": key or name,
        "name_raw": name,
        "price": price,
        "url": url or f"https://x.example/{abs(hash(name))}",
        "availability": "IN_STOCK",
    }


PHONES = [
    L("Смартфон Samsung Galaxy A56 5G 8/256GB Black", 5_300_000),
    L(
        "Samsung Galaxy A56 8/256GB Gray", 5_100_000
    ),  # same variant, other colour: colour is not identity
    L("Samsung Galaxy A56 12/512GB", 6_500_000),  # different RAM/storage: reject
    L("Samsung Galaxy A55 8/256GB", 4_900_000),  # different model: reject
    L("Чехол для Samsung Galaxy A56", 150_000),  # accessory: reject
]


def test_every_accepted_offer_is_kept_cheapest_first():
    t = Target("Samsung Galaxy A56 8/256GB", "smartphones")
    offers = match_target(t, "uzum", index_by_brand(PHONES, "smartphones"))
    assert [o.price for o in offers] == [5_100_000, 5_300_000]
    assert all(o.market == "uzum" and o.target == t.name for o in offers)
    assert offers[0].url and offers[0].score >= 30


def test_other_variants_and_accessories_are_never_accepted():
    t = Target("Samsung Galaxy A56 8/256GB", "smartphones")
    names = {o.listing_name for o in match_target(t, "uzum", index_by_brand(PHONES, "smartphones"))}
    assert not any("12/512" in n or "A55" in n or "Чехол" in n for n in names)


def test_non_phone_category_uses_the_lower_threshold():
    assert accept_threshold("smartphones") == 30
    assert accept_threshold("televisions") == NON_PHONE_ACCEPT == 25
    tvs = [
        L('Телевизор Samsung UE55DU7100UXUZ 55" 4K', 6_800_000),
        L("Телевизор Samsung UE50DU7100UXUZ", 5_300_000),
    ]
    t = Target("Samsung UE55DU7100UXUZ", "televisions")
    offers = match_target(t, "olcha", index_by_brand(tvs, "televisions"))
    assert [o.price for o in offers] == [6_800_000]  # a perfect TV match scores exactly 25


def test_no_category_means_no_matching():
    assert match_target(Target("Samsung Galaxy A56", None), "uzum", {}) == []


def test_search_only_listings_are_matched_without_a_bucket():
    t = Target("Samsung Galaxy A56 8/256GB", "smartphones")
    offers = match_target(t, "mediapark", None, [PHONES[0], PHONES[2]])
    assert [o.price for o in offers] == [5_300_000]


def test_duplicate_listing_is_not_counted_twice():
    dup = L("Samsung Galaxy A56 8/256GB", 5_100_000, key="same", url="https://x.example/dup")
    t = Target("Samsung Galaxy A56 8/256GB", "smartphones")
    offers = match_target(t, "uzum", None, [dup, dict(dup)])
    assert len(offers) == 1


def test_name_delta_reports_what_the_matcher_ignored():
    assert name_delta("ASW-H12A4/FADR", "ASW-H12A4/LR1DI") != ""
    assert name_delta("Samsung Galaxy A56", "Samsung Galaxy A56") == ""
