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


def test_apple_WITH_separator_still_reads_ram():
    # olcha lists "Iphone Air Space Black 12/256 GB" -- explicit separator,
    # so it really is a memory pair even for Apple.
    assert mem("Iphone Air Space Black 12/256 GB", brand="apple") == (12, 256)


def test_single_unit_figure_classified_by_size():
    assert mem("Redmi A5 64GB") == (None, 64)
    assert mem("некий товар 8 GB") == (8, None)


def test_no_memory_at_all():
    assert mem("Чехол для iPhone 17", brand="apple") == (None, None)
