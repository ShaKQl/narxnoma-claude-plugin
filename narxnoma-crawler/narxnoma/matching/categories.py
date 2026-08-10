"""Non-phone identity vocabulary.

A phone's identity is a signature: brand + model + RAM + storage + colour + SIM.
A television's is not. A TV, fridge, oven or air conditioner is identified by
its **catalogue code** -- "UE55DU7100UXUZ", "RT47CG6442B1WT", "NV68A1145RS" --
optionally preceded by a model NAME ("Predator Helios Neo", "Serie 6", "Alba").
Everything else in the title is marketing.

That inverts two rules the phone matcher depends on, which is why this module
exists instead of a flag inside features.py:

1. **The SKU-code rule must not fire.** features.py discards mixed letter+digit
   tokens of five or more characters, because for a phone "sm-a175f" is a
   catalogue code and "a17" is the identity. For a TV there IS no friendlier
   name: the code *is* the product. Measured on the live catalogue, that single
   rule made 100% of ovens, and the great majority of TVs and fridges,
   permanently unkeyable.

2. **Alphabetic tokens must be kept.** features.py keeps a word only if it is a
   known MODEL_MODIFIER ("pro", "max", "note"), because for phones any other
   word is noise. Appliance model names are made of exactly such words --
   "Vostro", "ThinkPad", "Aspire", "Predator" -- and dropping them merges every
   Acer laptop of the same memory tier into one product.

Both relaxations WIDEN what counts as identity, so the risk they introduce is
splitting one product into several, never merging two into one. That is the
safe direction for this project: a duplicate page is a coverage bug, a merged
page is the exact defect the platform exists to prevent.

The instrument that keeps splitting under control is the stopword vocabulary
below. "Телевизор Artel UA43H3502 Android TV" and "Телевизор Artel UA43H3502"
are one product, so "android", "tv" and "smart" must never reach the key.
"""
import re

# Product-type nouns, Russian and Uzbek (Latin), across all six non-phone
# categories. These lead almost every title in the live catalogue and identify
# the CATEGORY, which is already an axis of the key -- so repeating them inside
# model_tokens adds nothing and splits "Смарт-телевизор X" from "Телевизор X".
CATEGORY_NOUNS: frozenset[str] = frozenset({
    # televisions
    "телевизор", "телевизоры", "телевизора", "televizor", "televizori",
    "telewizor", "тв", "tv",
    # laptops
    "ноутбук", "ноутбуки", "ноутбука", "noutbuk", "noutbuki", "laptop",
    "netbuk", "нетбук",
    # air conditioners
    "кондиционер", "кондиционеры", "кондиционера", "konditsioner",
    "konditsioneri", "kondisioner", "сплит", "система", "системы",
    # fridges
    "холодильник", "холодильники", "холодильника", "автохолодильник",
    "автохолодильники", "muzlatgich", "muzlatgichi", "sovutgich",
    "sovutgichi", "морозильник", "морозильники",
    # washers
    "стиральная", "стиральные", "стиральной", "машина", "машины", "машинка",
    "mashina", "mashinasi", "kir", "yuvish", "стирально", "сушильная",
    # ovens / hobs
    "духовой", "духовка", "духовки", "шкаф", "духовых", "духовые",
    "плита", "плиты", "плитка", "duxovka", "duxovkasi", "pech",
    "варочная", "панель", "вытяжка", "печь",
})

# Words that describe HOW the appliance works or is installed. Real words, real
# information -- and not identity: "Двухкамерный холодильник Artel HD455" and
# "Холодильник Artel HD455" are one fridge. Measured as head tokens on the live
# catalogue ("полуавтомат" 28, "автомат" 10, "бытовой" 5, "двухкамерный" 3).
DESCRIPTORS: frozenset[str] = frozenset({
    "полуавтомат", "полуавтоматическая", "автомат", "автоматическая",
    "двухкамерный", "двухкамерная", "однокамерный", "трехкамерный",
    "встраиваемый", "встраиваемая", "встраиваемые", "встроенный",
    "напольный", "настольная", "настенный", "колонный", "кассетный",
    "витринный", "бытовой", "бытовая", "промышленный",
    "газовая", "газовые", "газовый", "электрическая", "электрический",
    "комбинированная", "комбинированный", "индукционная", "индукционный",
    "безрамочный", "игровой", "игровая", "портативный", "переносной",
    "вертикальная", "горизонтальная", "фронтальная",
    "новый", "новая", "оригинал", "оригинальный",
})

# Marketing and platform words. These vary between listings of the SAME
# product, so any one of them reaching the key splits a real product in two.
# "Телевизор Artel UA43H3502 Android TV" vs "Телевизор Artel UA43H3502" is the
# measured case that motivates the list.
MARKETING: frozenset[str] = frozenset({
    "smart", "смарт", "android", "андроид", "google", "assistant", "webos",
    "tizen", "yandex", "алиса", "ai", "wifi", "wi", "fi", "bluetooth",
    "inverter", "invertor", "инвертор", "инверторный", "инверторная",
    "led", "qled", "oled", "nanocell", "frameless",
    "uhd", "fhd", "hd", "ultrahd", "fullhd", "4k", "8k", "2k",
    "dyuym", "дюйм", "дюйма", "дюймов",
    "eco", "premium", "series", "serie", "серия", "gen",
    # NOTE: "pro", "air", "max", "plus", "ultra", "lite", "mini" and "neo" are
    # deliberately ABSENT. They read as marketing on a phone, but outside
    # phones they are the model name itself -- a MacBook Air is not a MacBook
    # Pro, and "Predator Helios Neo" is not "Predator Helios". Stripping them
    # would merge genuinely different products, which is the one failure this
    # module must not have. features.py keeps them for phones for the same
    # reason (MODEL_MODIFIERS).
    "new", "новинка", "хит", "акция", "скидка", "подарок", "гарантия",
    "доставка", "бесплатно", "рассрочка", "кредит",
    "official", "официальный", "оригинальный",
    "energy", "class", "класс",
})

# Measurement units and their figures' companions. A capacity in litres or
# kilograms is a SPEC, and the same product is listed with and without it.
UNITS: frozenset[str] = frozenset({
    "кг", "kg", "л", "лт", "литр", "литров", "l", "см", "cm", "мм", "mm",
    "вт", "w", "квт", "kw", "в", "v", "гц", "hz", "об", "мин", "rpm",
    "btu", "btuh", "м", "m", "м2", "m2", "м3",
    "гб", "gb", "тб", "tb", "мб", "mb", "ram", "ssd", "hdd", "emmc",
    "ddr", "ddr3", "ddr4", "ddr5", "lpddr4", "lpddr5",
    "ips", "va", "tn",
})

# Processors and graphics. A laptop's CPU is a specification, not its name --
# and it only reaches the tokens when the retailer omits the "/" delimiter that
# usually fences the spec off. Measured: "Ноутбук Acer Aspire Snapdragon X1
# 26100" became a different product from "Ноутбук Acer Aspire".
#
# Bare part numbers ("1334U", "26100", "N4405") are deliberately NOT listed:
# they are indistinguishable from real model codes by shape, and the vendor
# words below are enough to catch the titles that carry them.
# "apple" is a BRAND, and "m1".."m4" are the identity of a MacBook -- an Air M4
# is not an Air M2. Both are deliberately absent for the same reason "pro" and
# "air" are absent from MARKETING.
PROCESSORS: frozenset[str] = frozenset({
    "intel", "amd", "qualcomm", "mediatek", "nvidia",
    "snapdragon", "ryzen", "core", "celeron", "pentium", "athlon", "atom",
    "i3", "i5", "i7", "i9", "u5", "u7", "u9",
    "rtx", "gtx", "geforce", "radeon", "iris", "arc", "vega", "graphics",
    "processor", "процессор", "видеокарта", "graphic",
})

#: Everything a non-phone model token must not be.
NON_MODEL: frozenset[str] = (
    CATEGORY_NOUNS | DESCRIPTORS | MARKETING | UNITS | PROCESSORS
)

# Categories where a RAM/storage figure is a real specification. A laptop has
# 16 GB and a 512 GB SSD; a television, fridge, oven, washer or air conditioner
# has neither.
#
# This matters because the phone extractor reads a LONE plausible capacity as
# storage, and the plausible-storage set (32, 64, 128, 256, 512) overlaps
# exactly with television diagonals and fridge capacities. Measured: "Телевизор
# Premier 32PRM840FSV" was keyed with storage_gb = 32 and rendered as
# "Телевизор Premier 32PRM840FSV 32 ГБ" -- a spec the product does not have,
# printed on the page, and worse, a key that SPLITS from the same television
# listed without its diagonal.
CATEGORIES_WITH_MEMORY: frozenset[str] = frozenset({"laptops"})

# A laptop listing's identity ends where its specification begins. Retailers
# delimit that boundary explicitly and consistently:
#     "Ноутбук Acer Predator Helios Neo 16S AI / U9-275HX / DDR5 32GB / ..."
# Everything after the first "/" is CPU, GPU, memory and panel -- specification,
# not name. Keeping it would key the laptop on its graphics card.
#
# This is the same instrument uzum.md section 5a already applies to uzum card
# titles (truncate at the first comma); the delimiter set is wider here because
# these are seven retailers' free-text titles rather than one API's field.
#
# Applied to model TOKENS only. Memory and colour are still read from the WHOLE
# title, so "Acer Aspire 8/512" keeps storage 512 and stays distinct from the
# 8/256 -- truncating those away would merge two real products.
_SPEC_DELIMITERS = re.compile(r"[/|(\[]")


def head_for_model(name: str) -> str:
    """The part of a title that names the product, before its specification."""
    if not name:
        return ""
    return _SPEC_DELIMITERS.split(name, 1)[0]


def cut_at_processor(tokens: list[str]) -> list[str]:
    """Drop everything from the first processor word onward.

    The "/" fence catches most laptop specifications, but retailers that omit
    it run the spec straight on from the name:

        "Ноутбук Acer Aspire Snapdragon X1 26100"
        "Ноутбук ASUS Vivobook 17 X1704VA Core 5-120U 16GB 512GB"

    A vendor word is a reliable marker that the name has ended, whereas the
    part numbers after it ("x1", "26100", "5") are indistinguishable from real
    model codes by shape -- which is why PROCESSORS lists only the words and
    this function handles the rest positionally.
    """
    for i, t in enumerate(tokens):
        if t in PROCESSORS:
            return tokens[:i]
    return tokens


# Product-line names. Identity treats every model token alike, but a NAME has
# to read the way the product is sold: "Vivobook Go 15", not "15 Go Vivobook".
# model_tokens is a frozenset, so display order has to be reconstructed, and
# alphabetical order puts the screen size first on almost every laptop.
FAMILY_WORDS: frozenset[str] = frozenset({
    # laptops
    "vivobook", "zenbook", "expertbook", "chromebook", "macbook", "thinkpad",
    "thinkbook", "ideapad", "yoga", "legion", "loq", "aspire", "swift",
    "predator", "nitro", "travelmate", "extensa", "pavilion", "envy",
    "elitebook", "probook", "omen", "victus", "vostro", "inspiron",
    "latitude", "precision", "xps", "modern", "prestige", "katana",
    "cyborg", "bravo", "sword", "raider", "stealth", "tuf", "rog", "gaming",
    # televisions / appliances product lines
    "bravia", "crystal", "frame", "serif", "neoqled", "smarttv",
    "alba", "naomi", "marvarid", "milagro", "apetito", "shaxrisabz",
    "grand", "forever", "city", "tashkent",
})


def ordered_non_phone_tokens(tokens: frozenset[str] | set[str]) -> list[str]:
    """Model tokens in the order a person writes them.

    Family name first ("Vivobook"), then the remaining words alphabetically,
    then catalogue codes, then bare figures such as a diagonal or a BTU class.
    Ordering is DISPLAY ONLY -- identity is the unordered set, so two listings
    that name the same tokens in different orders remain one product.
    """
    families, words, codes, figures = [], [], [], []
    for t in sorted(tokens):
        if t in FAMILY_WORDS:
            families.append(t)
        elif t.isdigit():
            figures.append(t)
        elif any(c.isdigit() for c in t):
            codes.append(t)
        else:
            words.append(t)
    figures.sort(key=lambda x: (len(x), x))
    return families + words + codes + figures


# Things sold ALONGSIDE the product, in the product's own category feed. A
# laptop bag is returned by a laptop sweep, carries a brand and a code, and so
# forms a perfectly valid key -- "Rivacase 7531" became a laptop. Unlike the
# phone case, nothing downstream rejects it: the price fence passes it and the
# key system accepts it, so it reaches the catalogue as a product.
_ACCESSORY = re.compile(
    r"\b("
    r"sumka\w*|сумк\w*|chexol\w*|чехол\w*|"
    r"kronshteyn\w*|кронштейн\w*|подставк\w*|крепление|крепление\w*|"
    r"pult\w*|пульт\w*|kabel\w*|кабел\w*|переходник\w*|удлинител\w*|"
    r"filtr\w*|фильтр\w*|мешок|мешк\w*|шланг\w*|картридж\w*|"
    r"lampa\w*|лампочк\w*|щетк\w*|щётк\w*|насадк\w*|"
    r"аксессуар\w*|aksessuar\w*|салфетк\w*|чистящ\w*|"
    r"стабилизатор\w*|подключение|установка|монтаж"
    r")\b",
    re.I,
)

# The same shape the phone denylist uses (sources/not_a_phone.py): a title that
# LEADS with the product noun is the product, and an accessory word inside it
# describes what is in the box. "Телевизор ... с пультом" is a television.
_LEADS_WITH_CATEGORY_NOUN = re.compile(
    r"^\s*(" + "|".join(sorted(CATEGORY_NOUNS, key=len, reverse=True)) + r")\b",
    re.I,
)


def is_accessory(name: str | None, category: str = "smartphones") -> bool:
    """True when a title in a category feed is an accessory, not the product.

    Conservative in the direction this project always chooses: a title that
    names its own category first is never an accessory, so the failure mode is
    admitting a bag rather than losing a laptop.
    """
    if category == "smartphones" or not name:
        return False
    if _LEADS_WITH_CATEGORY_NOUN.match(name.strip()):
        return False
    return bool(_ACCESSORY.search(name))


def is_model_token(token: str) -> bool:
    """True when a token may stand as part of a non-phone product's identity.

    Deliberately permissive about SHAPE and strict about VOCABULARY: any word
    or code survives unless it is a known category noun, descriptor, marketing
    word or unit. Shape cannot separate "wgk264zxme" (identity) from "ddr5"
    (specification) -- both are letters plus digits -- so the vocabulary does
    the work, and every entry in it was measured against live titles.
    """
    if not token or token in NON_MODEL:
        return False
    # A bare unit-suffixed figure is a spec: "43дюйма", "512gb", "1200об".
    if re.fullmatch(r"\d+(?:gb|гб|tb|тб|кг|kg|л|lt|см|cm|вт|w|hz|гц|об|rpm|дюйм\w*)", token):
        return False
    # A lone letter is never identity; it is a stray initial from a split code.
    return len(token) > 1
