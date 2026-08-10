"""Non-phone identity: the rules a television needs and a phone must not get.

Every listing quoted here is REAL -- taken from the live catalogue during the
measurement that motivated this module. Under the phone-only extractor, 75% of
2,076 harvested non-phone offers produced no key at all and never reached the
site; the cases below are the mechanisms behind that.
"""
import pytest

from narxnoma.matching.brands import brand_label
from narxnoma.matching.categories import (
    is_accessory,
    is_model_token,
    ordered_non_phone_tokens,
)
from narxnoma.matching.features import extract_features
from narxnoma.matching.keys import display_name, variant_key
from narxnoma.matching.normalize import normalize
from narxnoma.pipeline.cluster import is_wellformed


# --- the catalogue code IS the identity -------------------------------------

@pytest.mark.parametrize("name,category", [
    ("Телевизор Samsung UE55DU7100UXUZ", "televisions"),
    ("Холодильник Samsung RT47CG6442B1WT", "fridges"),
    ("Духовой шкаф Samsung NV68A1145RS/WT", "ovens"),
    ("Стиральная машина Samsung WW60AG4S00CELD, белый", "washers"),
    ("Кондиционер TCL TAC-CT12INV/RIF, белый", "acs"),
])
def test_appliance_model_code_survives_as_identity(name, category):
    # The phone extractor discards mixed letter+digit tokens of 5+ characters
    # as catalogue noise. For an appliance that token is the whole name, and
    # discarding it made 100% of ovens unkeyable.
    f = extract_features(name, category)
    assert f.brand == "samsung" if "Samsung" in name else f.brand is not None
    assert f.model_tokens, f"{name} yielded no model tokens"
    assert variant_key(f, "dual", category) is not None


def test_phone_still_discards_sku_codes():
    # The same input under the phone rules must be unchanged: "a075f" is a
    # catalogue code and "a07" is the identity.
    f = extract_features("SAMSUNG SM-A075F A07 4/64 Black")
    assert "a075f" not in f.model_tokens
    assert "a07" in f.model_tokens


# --- brand vocabulary --------------------------------------------------------

@pytest.mark.parametrize("name,category,brand", [
    ("Телевизор Artel SMART A32PHCH010 Google tv HD", "televisions", "artel"),
    ("Ноутбук Lenovo ThinkPad T14 Gen 4 21HD0077US", "laptops", "lenovo"),
    ("Ноутбук HP EliteBook 14", "laptops", "hp"),
    ("Ноутбук Hp15-fd0043nq i3-1315U", "laptops", "hp"),
    ("Холодильник Bosch KGN56CX30U", "fridges", "bosch"),
    ("Кондиционер LG Dual Cool Inverter I24CGH", "acs", "lg"),
    ("Газовая плита PRЕMIER Eco BT60F-40VW", "ovens", "premier"),
    ("MacBook Air 13-inch M4 16/256GB Silver", "laptops", "apple"),
])
def test_appliance_brands_are_recognised(name, category, brand):
    assert extract_features(name, category).brand == brand


@pytest.mark.parametrize("name", [
    "Ноутбук Acer Aspire зарядное устройство charger",   # "arg" inside "charger"
    "Телевизор большой large screen",                     # "arg" inside "large"
])
def test_short_brand_names_are_not_matched_as_substrings(name):
    # The appliance vocabulary contains "arg", "lg" and "hp". A substring scan
    # -- which is what the phone path does -- finds "arg" inside "charger" and
    # "large", inventing a manufacturer out of an adjective.
    assert extract_features(name, "laptops").brand != "arg"


# --- vocabulary is the precision instrument ---------------------------------

def test_marketing_words_never_split_one_product_in_two():
    a = extract_features("Телевизор Artel UA43H3502 Android TV", "televisions")
    b = extract_features("Телевизор Artel UA43H3502", "televisions")
    assert a.model_tokens == b.model_tokens
    assert variant_key(a, "dual", "televisions") == variant_key(b, "dual", "televisions")


def test_descriptors_never_split_one_product_in_two():
    a = extract_features("Двухкамерный холодильник Artel HD455", "fridges")
    b = extract_features("Холодильник Artel HD455", "fridges")
    assert variant_key(a, "dual", "fridges") == variant_key(b, "dual", "fridges")


@pytest.mark.parametrize("word", ["pro", "air", "max", "plus", "neo"])
def test_designators_are_kept_because_they_name_the_product(word):
    # A MacBook Air is not a MacBook Pro. These read as marketing on a phone,
    # so the temptation is to strip them everywhere -- which would merge two
    # genuinely different products, the one failure this module must not have.
    assert is_model_token(word)


def test_macbook_air_and_pro_are_different_products():
    air = variant_key(extract_features("MacBook Air 13 M4 256GB", "laptops"), "dual", "laptops")
    pro = variant_key(extract_features("MacBook Pro 13 M4 256GB", "laptops"), "dual", "laptops")
    assert air is not None and pro is not None
    assert air != pro


# --- a laptop's identity ends where its specification begins ----------------

def test_laptop_spec_after_the_delimiter_is_not_identity():
    f = extract_features(
        "Ноутбук Acer Predator Helios Neo 16S AI / U9-275HX / DDR5 32GB / RTX 5060",
        "laptops",
    )
    assert {"predator", "helios", "neo"} <= f.model_tokens
    assert "rtx" not in f.model_tokens and "5060" not in f.model_tokens


def test_storage_is_still_read_from_the_whole_laptop_title():
    # Truncation is for model tokens only: memory must survive it, or an
    # Aspire 512 and an Aspire 256 become one product.
    small = extract_features("Ноутбук Acer Aspire 8/256", "laptops")
    large = extract_features("Ноутбук Acer Aspire 8/512", "laptops")
    assert small.storage_gb == 256 and large.storage_gb == 512
    assert variant_key(small, "dual", "laptops") != variant_key(large, "dual", "laptops")


# --- a television has no RAM -------------------------------------------------

@pytest.mark.parametrize("category", ["televisions", "fridges", "acs", "washers", "ovens"])
def test_memory_is_absent_outside_phones_and_laptops(category):
    # The plausible-storage set (32, 64, ...) overlaps exactly with television
    # diagonals. "Телевизор Premier 32PRM840FSV" was keyed with storage 32 and
    # rendered as "... 32 ГБ" -- a spec the product does not have.
    f = extract_features("Телевизор Premier 32PRM840FSV 32", category)
    assert f.ram_gb is None and f.storage_gb is None


def test_television_diagonal_is_legitimate_identity():
    # "Телевизор MoonX 32" is a real product whose diagonal is the only thing
    # distinguishing it. The phone capacity guard refused exactly these.
    k = variant_key(extract_features('Телевизор MoonX 32" Черный', "televisions"),
                    "dual", "televisions")
    assert k is not None
    assert is_wellformed(k)


def test_capacity_guard_still_protects_phones():
    from narxnoma.matching.keys import VariantKey
    bad = VariantKey("apple", frozenset({"17", "256"}), None, 512, "black", "dual")
    assert not is_wellformed(bad)


# --- mixed-script titles -----------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Tелевизор Artel", "телевизор artel"),        # Latin T in a Russian word
    ("Cтиральная машина", "стиральная машина"),    # Latin C
    ("Стиральная машинa", "стиральная машина"),    # Latin a
])
def test_latin_letters_inside_russian_words_are_folded(raw, expected):
    assert normalize(raw) == expected


def test_cyrillic_letters_inside_a_model_code_are_folded_to_latin():
    # "Автохолодильник Alpicool С20" -- a CYRILLIC С inside a code every other
    # listing writes with a Latin C. Two spellings, one product.
    assert normalize("Alpicool С20") == normalize("Alpicool C20")


def test_a_latin_brand_with_one_cyrillic_letter_keeps_its_brand():
    # "PRЕMIER" is Latin with a single Cyrillic Е. Folding toward Cyrillic
    # produced the unmatchable "рrемiеr" and lost the brand entirely.
    assert normalize("PRЕMIER") == "premier"


def test_single_script_tokens_are_left_alone():
    assert normalize("Vivobook") == "vivobook"
    assert normalize("телевизор") == "телевизор"


# --- accessories -------------------------------------------------------------

def test_a_laptop_bag_is_not_a_laptop():
    assert is_accessory("Rivacase 7531 Black Eco 15.6 Noutbuk sumkasi", "laptops")


def test_a_product_that_names_its_own_category_first_is_the_product():
    # An accessory word inside such a title describes what is in the box.
    assert not is_accessory("Телевизор Samsung UE55 с пультом", "televisions")
    assert not is_accessory("Ноутбук Acer Aspire в сумке", "laptops")


def test_accessory_rule_never_applies_to_phones():
    # Phones have their own denylist (sources/not_a_phone.py); running both
    # would drop the real phones its regression tests exist to protect.
    assert not is_accessory("Чехол для Samsung Galaxy", "smartphones")


# --- one product, however the retailer decorates it -------------------------

def _key(name, category):
    return variant_key(extract_features(name, category), "dual", category)


@pytest.mark.parametrize("category,a,b", [
    # Finish, capacity and internal code fragments, all around ONE code.
    ("fridges", "Холодильник Samsung RB29FERNDSA",
     "SAMSUNG RB29FERNDSA 290L Sovutgichi"),
    ("fridges", "Холодильник Samsung RT62K7110SL",
     "Холодильник Samsung Inox RT62K7110SL"),
    ("fridges", "Холодильник LG GN-B392SMBB Inverter",
     "LG GN-B392SMBB.APZQCIS Muzlatgichi"),
    ("acs", "Кондиционер Artel Everest 12 Inverter ARTSID3AW12BE",
     "Кондиционер Artel Everest ARTSID3AW12BE Inverter"),
    ("acs", "Artel 12HS S SIR1W12BE Konditsioneri",
     "Настенный кондиционер Artel S Inverter SIR1W12BE"),
    ("televisions", "Телевизор Artel SMART A32PHCH010 Google tv HD",
     "Телевизор Artel A32PHCH010 32\", чёрный"),
    ("televisions", "Samsung UE55DU7100UXUZ Smart Televizori",
     "Телевизор Samsung UE55DU7100UXUZ Smart, черный"),
])
def test_one_catalogue_code_is_one_product(category, a, b):
    ka, kb = _key(a, category), _key(b, category)
    assert ka is not None and kb is not None
    assert ka == kb, f"{a!r} and {b!r} should be one product"


def test_a_title_without_a_code_keeps_its_distinguishing_figure():
    # Nothing else identifies these, so the figure must survive.
    assert _key("Кондиционер Midea Naomi PRO AI Inverter 09", "acs") != \
           _key("Кондиционер Midea Naomi PRO AI Inverter 24", "acs")
    assert _key('Телевизор MoonX 32"', "televisions") is not None


def test_unknown_colour_words_never_become_identity():
    # Colour is deliberately not identity outside phones. A finish word the
    # palette does not know must be dropped, not promoted to a model token --
    # these three split one fridge into three products at three prices.
    base = _key("Холодильник Artel Frost HD276FND", "fridges")
    assert base == _key("Холодильник Artel Frost Матовый HD276FND", "fridges")
    assert base == _key("Холодильник Artel Frost Асфальт Мокрый HD276FND", "fridges")


def test_a_laptop_cpu_is_not_its_name():
    # Only bites when the retailer omits the "/" that usually fences the spec.
    assert _key("Ноутбук Acer Aspire Snapdragon X1 26100", "laptops") == \
           _key("Ноутбук Acer Aspire", "laptops")


def test_macbook_generations_stay_apart():
    # "m4" looks like a spec token and is not: it is the identity of the
    # machine, so PROCESSORS must not contain it.
    assert _key("MacBook Air 13 M4 256GB", "laptops") != \
           _key("MacBook Air 13 M2 256GB", "laptops")


# --- display -----------------------------------------------------------------

def test_family_name_leads_the_model_string():
    # A frozenset has no order, and alphabetical order puts the screen size
    # first on almost every laptop: "ASUS 15 Go Vivobook".
    assert ordered_non_phone_tokens({"15", "go", "vivobook"}) == ["vivobook", "go", "15"]


def test_codes_come_before_bare_figures():
    assert ordered_non_phone_tokens({"55", "ue55du7100uxuz"}) == ["ue55du7100uxuz", "55"]


def test_apple_label_is_not_iphone_outside_phones():
    # BRAND_LABELS maps apple -> "Apple iPhone" because the word iPhone is
    # stripped from phone names and has to be put back. A MacBook is also
    # brand apple, so the phone label renders "Ноутбук Apple iPhone MacBook".
    assert brand_label("apple", "laptops") == "Apple"
    assert brand_label("apple", "smartphones") == "Apple iPhone"


def test_non_phone_display_name_reads_naturally():
    k = variant_key(
        extract_features("Телевизор Samsung UE55DU7100UXUZ", "televisions"),
        "dual", "televisions",
    )
    assert display_name(k) == "Телевизор Samsung UE55DU7100UXUZ"
