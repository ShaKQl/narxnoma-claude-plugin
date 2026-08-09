"""Denylist of things that are not phones.

texnomart items carry NO category field -- verified against the recorded
fixture, unlike idea (category_id) and beemarket (a category endpoint). The
only usable signal is the product-type noun the retailer appends to the
name, which is weaker evidence, so this is a DENYLIST of things that are
not phones rather than an allowlist of things that are: an allowlist would
silently drop any phone whose name lacks the expected word, and losing a
real phone is worse than admitting an accessory the price fence and the
matcher still get a chance to reject.

Measured on 467 texnomart live offers: 142 (30.4%) are not phones, and 15
of them had already become canonical PRODUCTS -- a tablet carries a brand,
a memory pair and a colour, so it forms a full key exactly as a phone
does. alifshop's unfiltered fallback (brands without a "Смартфоны" bucket,
e.g. ASUS) is the same shape: 38 laptop offers became products.
"""
import re

_NOT_A_PHONE = re.compile(
    r"\b("
    r"plansh\w*|планшет\w*|noutbuk\w*|ноутбук\w*|"
    r"vivobook|zenbook|matebook|chromebook|macbook|ideapad|thinkpad|"
    r"zaryadk\w*|зарядн\w*|"
    r"plyonka\w*|плёнк\w*|пленк\w*|"
    r"quloqchin\w*|наушник\w*|kabel\w*|кабел\w*|powerbank|"
    r"televizor\w*|телевизор\w*|soat\w*|watch|часы|"
    r"matepad|ipad|galaxy tab"
    r")\b",
    re.I,
)

# NOTE: "adapter/адаптер" is deliberately NOT in the denylist. Measured on
# the live catalogue: "Смартфон Samsung Galaxy A37 5G: ... USB-адаптер
# 8/128+ 25 Вт ..." is a REAL PHONE whose title advertises the bundled
# charger, and 6 such offers were already canonical products. A standalone
# "USB-адаптер 25 Вт Samsung" carries no memory pair, so it can never form
# a variant key -- it is unkeyable and lands in unresolved_offer, never in
# the catalogue. Admitting noise the key-system already rejects is cheaper
# than losing a phone, which is this filter's one unforgivable failure
# mode. "зарядн\w*" stays: "Зарядное устройство ..." is the title shape of
# genuine charger listings.

# "чехол" is a case -- and also a GIFT. "Смартфон Samsung Galaxy S25 ultra в
# подарок чехол 12/256 ГБ" is a real phone sold with a free case; a bare
# `чехол\w*` dropped it from the live catalogue measurement. Only the
# accessory sense counts (a case listing, no gift mention nearby).
_CASE = re.compile(r"\b(chexol\w*|чехол\w*)\b", re.I)
_GIFT = re.compile(r"подарок", re.I)

# A title that STARTS with a phone word is a phone listing; accessory nouns
# in it are bundled features, not the product. Measured: "Смартфон Samsung
# Galaxy A37 5G: мощные технологии USB-адаптер 8/128+ 25 Вт" (real phone
# with the charger in the box) vs "Samsung EP-T6010NBEGRU 60W Black
# adapteri" (a standalone charger). The adapter itself stays a drop signal
# for titles that do not start with a phone word.
_PHONE_START = re.compile(
    r"^\s*(смартфон\w*|smartfon\w*|smartphone\w*|телефон\w*|iphone\w*)",
    re.I,
)

# "стекло" is a screen protector -- and ALSO a colour. "Смартфон OPPO A3
# (6/128) Черное стекло" is a real phone in black glass, and a bare
# `стекл\w*` dropped three of them. Only the accessory sense counts, so the
# word must be qualified. When in doubt about a material word, leave it out:
# this filter's failure mode must be admitting noise, never losing a phone.
_PROTECTOR = re.compile(r"(защитн\w*\s+стекл\w*|стекл\w*\s+защитн\w*|"
                        r"himoya\w*\s+shisha\w*)", re.I)


def is_phone_listing(listing) -> bool:
    """False for the accessories and non-phone devices these sources mix in.

    Shared by texnomart (no category field at all) and alifshop (whose
    category facet is absent for non-phone brands, so its sweep falls back to
    unfiltered). Applied in sweep() only -- parse() stays a faithful pure
    function of one response.
    """
    name = listing.name_raw or ""
    if _PHONE_START.match(name):
        # A phone's marketing title: accessory words ("USB-адаптер",
        # "в подарок чехол") describe what is IN THE BOX, not the product.
        return True
    if _NOT_A_PHONE.search(name) or _PROTECTOR.search(name):
        return False
    case = _CASE.search(name)
    if case:
        # Only the accessory sense counts: a case listing, not a phone sold
        # with a free case. The gift mention sits within ~16 chars on either
        # side of the word in every observed shape ("в подарок чехол",
        # "чехол в подарок").
        if not _GIFT.search(name[max(0, case.start() - 16): case.end() + 16]):
            return False
    return True