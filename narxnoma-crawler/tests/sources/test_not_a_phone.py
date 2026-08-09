"""Denylist tests: tablets/laptops/accessories must never reach the
catalogue; real phones -- including ones with no product-type noun -- must
always survive. Failure mode is admitting noise, never losing a phone."""

from narxnoma.sources.base import Listing
from narxnoma.sources.not_a_phone import is_phone_listing


def _listing(name: str) -> Listing:
    return Listing(store_slug="texnomart", source_key="k", name_raw=name,
                   price=2_000_000, url="https://texnomart.uz/x",
                   availability="IN_STOCK")


def test_tablets_and_laptops_are_not_phones():
    """Measured live: 142 of texnomart's 467 offers are not phones, and 15
    became canonical PRODUCTS -- a tablet has a brand, a memory pair and a
    colour, so it forms a full key exactly like a phone does.
    """
    for name in [
        "Samsung Tab A11 Wi-Fi 8/128GB Gray Plansheti",
        "Honor Pad X7 4/128GB Space Grey Plansheti",
        'Huawei MatePad 11.5"S PaperMatte WIFI 12/256GB Grey Plansheti',
        "Asus VivoBook 15 i5/8/512 Silver Noutbuki",
        "Apple iPad 11 A3354 A16 6/128GB Wi-Fi Blue Plansheti",
        "Зарядное устройство Samsung 25 Вт",
        "Наушники Samsung Galaxy Buds черные",
        "Телевизор Samsung 43 дюйма",
    ]:
        assert not is_phone_listing(_listing(name)), name


def test_real_phones_survive():
    for name in [
        "Samsung Galaxy A17 4G 8/256GB Qora",
        "Apple iPhone 17 Pro 256GB Silver",
        "Xiaomi Redmi Note 15 12/256 GB Black",
        "Honor X9d 12/256GB Black",
        "Смартфон OPPO A3 (6/128) Черное стекло",  # colour, not a protector
        "Смартфон Motorola G75 8/256 GB Черное стекло",
    ]:
        assert is_phone_listing(_listing(name)), name


def test_the_rule_is_a_denylist_not_an_allowlist():
    """A phone whose name carries no product-type noun at all must pass.
    An allowlist of phone words would silently drop it, and losing a real
    phone is worse than admitting the odd accessory -- which the price
    fence and the matcher then get a second chance at.
    """
    assert is_phone_listing(_listing("Nothing Phone 3a 8/256 Grey"))
    assert is_phone_listing(_listing("ZTE Blade V70 8/256"))


def test_protector_requires_the_accessory_sense():
    assert not is_phone_listing(_listing("Защитное стекло iPhone 17 прозрачное"))
    assert not is_phone_listing(_listing("Стекло защитное Honor X9d"))
    assert not is_phone_listing(_listing("Himoya shishasi Redmi Note 15"))


def test_case_word_requires_the_accessory_sense():
    """A phone sold WITH a free case is still a phone. The pre-flight caught
    'Черное стекло' as a colour; the live measurement caught 'в подарок
    чехол' as a gift. Same shape: material/accessory word used in a phone
    name must not drop the phone.
    """
    assert is_phone_listing(
        _listing("Смартфон Samsung Galaxy S25 ultra в подарок чехол 12/256 ГБ Бежевый меланж")
    )
    assert is_phone_listing(_listing("Смартфон Samsung S25 чехол в подарок 8/256 Черный"))
    assert not is_phone_listing(_listing("Чехол для Samsung A17 силиконовый"))
    assert not is_phone_listing(_listing("Samsung Galaxy A17 Chexol transparent"))


def test_a_phone_title_with_bundled_charger_survives():
    """Measured: 6 uzum offers were 'Samsung Galaxy A37 5G: мощные
    технологии USB-адаптер 8/128+ ...' -- a REAL phone whose title names
    the charger in the box; all six were canonical products. And the
    standalone 'Samsung EP-T6010NBEGRU 60W Black adapteri' is unkeyable
    (no memory pair), so admitting it costs nothing -- it can only ever
    land in unresolved_offer, never in the catalogue. Losing a phone is
    the one unforgivable failure mode; this class of noise is not.
    """
    assert is_phone_listing(
        _listing("Samsung Galaxy A37 5G: мощные технологии USB-адаптер 8/128+ 25 Вт (оригинальный) Тёмно-зелёный")
    )
    assert is_phone_listing(_listing("USB-адаптер 25 Вт (оригинальный) Samsung"))
    assert is_phone_listing(_listing("Samsung EP-T6010NBEGRU 60W Black adapteri"))
    assert not is_phone_listing(_listing("Зарядное устройство Samsung 25 Вт USB-адаптер"))