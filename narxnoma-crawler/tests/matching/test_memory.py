from narxnoma.matching.memory import extract_memory
from narxnoma.matching.normalize import normalize


def mem(raw, brand=None):
    return extract_memory(raw, normalize(raw), brand)


def test_collects_all_unit_bearing_figures():
    # A re.search for the FIRST unit match returns 8 -> storage=8 -> every
    # such listing rejected. This killed all Honor 600 matches on uzum.
    assert mem("Honor 600 8ГБ/256ГБ") == (8, 256)
    assert mem("Xiaomi 12GB+512GB") == (12, 512)


def test_terabytes_convert_to_gb():
    assert mem("iPhone 17 Pro Max 1 ТБ", brand="apple") == (None, 1024)


def test_lookbehind_stops_model_being_read_as_memory():
    # Without the lookbehind, "Samsung Galaxy A17 128GB" parses the pair
    # "17 128" and yields ram=17.
    ram, storage = mem("Samsung Galaxy A17 128GB", brand="samsung")
    assert storage == 128
    assert ram != 17


def test_bare_pair_is_ram_and_storage_for_non_apple():
    assert mem("Samsung Galaxy A17 6 128", brand="samsung") == (6, 128)


def test_slash_pair_is_ram_and_storage():
    assert mem("Honor X9d 12/256 GB", brand="honor") == (12, 256)


def test_apple_bare_pair_is_NOT_ram():
    # THE BUG: "iPhone 16 256 GB" has the same shape as "12/256 GB".
    # Reading 16 as RAM moved it into reserved_nums, deleting the model
    # number from model_tokens, so iPhone 16 / 17 / Air all matched.
    # Apple never publishes RAM in consumer names.
    assert mem("Apple iPhone 16 256 GB Black", brand="apple") == (None, 256)
    assert mem("Apple iPhone 17 256 ГБ", brand="apple") == (None, 256)


def test_apple_WITH_separator_STILL_yields_no_ram():
    # SUPERSEDED behaviour. This test previously asserted (12, 256): an
    # explicit separator was taken as proof that a figure really was RAM,
    # even for Apple. That exemption is exactly what split one phone into two
    # canonical products, so Apple RAM suppression is now global and this
    # listing must yield no RAM at all. The storage reading is unchanged.
    assert mem("Iphone Air Space Black 12/256 GB", brand="apple") == (None, 256)


def test_single_unit_figure_classified_by_size():
    assert mem("Redmi A5 64GB") == (None, 64)
    assert mem("некий товар 8 GB") == (8, None)


def test_no_memory_at_all():
    assert mem("Чехол для iPhone 17", brand="apple") == (None, None)


def test_samsung_model_number_is_not_read_as_ram_fold():
    # Real listing: "Смартфон Samsung Galaxy Z Fold 7 512 ГБ Jet Black".
    # The model number 7 has the same "small int + big int" shape as a
    # bare RAM/storage pair. Samsung publishes RAM, so it isn't covered by
    # BRANDS_WITHOUT_PUBLISHED_RAM -- the plausibility set is what stops it.
    assert mem("Смартфон Samsung Galaxy Z Fold 7 512 ГБ Jet Black", brand="samsung") == (
        None,
        512,
    )


def test_samsung_model_number_is_not_read_as_ram_flip():
    # Real listing: "Смартфон Samsung Galaxy Z Flip 7 256 ГБ Jet Black".
    assert mem("Смартфон Samsung Galaxy Z Flip 7 256 ГБ Jet Black", brand="samsung") == (
        None,
        256,
    )


def test_scans_past_implausible_pair_to_find_real_memory():
    # Real listing: "Redmi A7 Pro smartfoni 6.9\" 120Hz 6000 mAh 13MP AI
    # 4/128 Qora". The marketing blurb contains "9 120" (from 6.9" and
    # 120Hz), which has the shape of a memory pair but isn't one; scanning
    # must skip it and find the real "4/128" pair.
    assert mem(
        'Redmi A7 Pro smartfoni 6.9" 120Hz 6000 mAh 13MP AI 4/128 Qora',
        brand="xiaomi",
    ) == (4, 128)


def test_watch_size_is_not_plausible_storage():
    # Real listing: "Samsung Galaxy Watch 5 44mm Graphite". 44 is not a
    # plausible storage size, so neither RAM nor storage should be read.
    assert mem("Samsung Galaxy Watch 5 44mm Graphite", brand="samsung") == (None, None)


def test_explicit_unit_case_still_works():
    assert mem("Honor 600 8ГБ/256ГБ") == (8, 256)


def test_two_digit_ram_after_two_digit_model_number():
    # Real listing: "Redmi Note 15 12/256 ГБ, черный". normalize() turns
    # this into "redmi note 15 12 256 гб черный" -- the model number "15"
    # sits directly before the RAM "12", so a non-overlapping scan finds
    # only ("15", "12"), which is correctly rejected as implausible
    # storage, and never backtracks to see the real ("12", "256") pair.
    assert mem("Redmi Note 15 12/256 ГБ, черный", brand="xiaomi") == (12, 256)


def test_two_digit_ram_after_two_digit_model_number_16():
    # Real listing: "Redmi Note 15 16/512 ГБ". Same trap as above with a
    # different RAM size, confirming the fix isn't specific to "12".
    assert mem("Redmi Note 15 16/512 ГБ", brand="xiaomi") == (16, 512)


def test_single_digit_ram_after_model_number_still_works():
    # Real listing: "Redmi Note 15 8/256 ГБ, черный". The single-digit RAM
    # case always worked (a 1-digit run can't be misread as a 2-4 digit
    # storage figure), so this pins the pre-fix behaviour against regression.
    assert mem("Redmi Note 15 8/256 ГБ, черный", brand="xiaomi") == (8, 256)


def test_apple_unit_bearing_pair_yields_no_ram():
    # THE SPLIT: the BRANDS_WITHOUT_PUBLISHED_RAM guard used to sit only on
    # the bare-pair fallback, so "12/256GB" reached the unit-bearing pass
    # untouched and returned ram=12, while "iPhone 17 Pro 256 ГБ" returned
    # None. One phone, two canonical products (apple-17-pro-12-256-silver and
    # apple-17-pro-256-silver): a split offer pool and two displayed prices.
    # Apple publishes no RAM, so any such figure is a reseller's own wording.
    assert mem("iPhone 17 Pro 12/256GB Silver", brand="apple") == (None, 256)


def test_non_apple_unit_bearing_pair_still_reads_ram():
    # The suppression must be brand-scoped, not blanket: brands that DO
    # publish RAM keep it as identity, or 8/256 and 12/256 would merge.
    assert mem("Honor X9d 12/256GB Black", brand="honor") == (12, 256)
