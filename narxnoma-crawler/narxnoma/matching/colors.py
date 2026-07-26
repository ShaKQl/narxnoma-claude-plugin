"""Colour vocabulary.

Only BASE colour words are mapped. Finish/qualifier words (velvet, тёмно,
меланж) must never map: "Velvet Grey" -> {black, gray} would match a Black
listing. The base colour word is always present anyway, so qualifiers add
nothing but false positives.

An unresolvable colour must REJECT, not pass. Treating it as a wildcard let
"Конфетный" and "Хром" match both Awesome Gray and Awesome Navy at once.
"""

COLOR_MAP: dict[str, str] = {
    # --- english base words ---
    "black": "black", "midnight": "black", "obsidian": "black", "graphite": "black",
    "white": "white", "moonlight": "white", "cloud": "white",
    "silver": "silver", "meteor": "silver", "titanium": "silver",
    "gray": "gray", "grey": "gray", "space": "gray", "charcoal": "gray",
    "gold": "gold", "desert": "gold", "sunrise": "gold", "champagne": "gold",
    "sandy": "gold", "sand": "gold",
    "blue": "blue", "cyan": "blue", "ocean": "blue", "aqua": "blue",
    "navy": "blue", "sky": "blue", "glacier": "blue", "denim": "blue",
    "red": "red", "scarlet": "red",
    "brown": "brown", "reddish": "brown", "coffee": "brown",
    "green": "green", "sage": "green", "mint": "green", "emerald": "green",
    "jade": "green", "forest": "green", "marrs": "green", "agate": "green",
    "purple": "purple", "violet": "purple", "cobalt": "purple",
    "lavender": "purple", "lilac": "purple", "plum": "purple",
    "orange": "orange", "cosmic": "orange", "amber": "orange", "coral": "orange",
    "pink": "pink", "rose": "pink",
    "beige": "beige", "cream": "beige", "ivory": "beige",
    "burgundy": "burgundy", "wine": "burgundy",
    "yellow": "yellow", "lime": "yellow",
    # --- russian (uzum Цвет values; see parsers/uzum.md section 8) ---
    "черный": "black", "черное": "black", "черная": "black",
    "угольный": "gray", "серый": "gray",
    "серебряный": "silver", "серебристый": "silver", "титановый": "silver",
    "синий": "blue", "голубой": "blue", "ледяной": "blue", "бирюзовый": "blue",
    "фиолетовый": "purple", "лавандовый": "purple", "сиреневый": "purple",
    "зеленый": "green", "мятный": "green",
    "оранжевый": "orange", "манго": "orange",
    "золотой": "gold", "золотистый": "gold", "песочный": "gold",
    "бежевый": "beige", "кремовый": "beige",
    "белый": "white", "молочный": "white",
    "бордовый": "burgundy", "коричневый": "brown", "алый": "red",
    "красный": "red", "розовый": "pink", "желтый": "yellow",
    # --- uzbek (uzum card/model strings) ---
    "qora": "black", "oq": "white", "kumush": "silver", "kulrang": "gray",
    "tilla": "gold", "oltin": "gold", "sariq": "yellow", "yashil": "green",
    "kok": "blue", "moviy": "blue", "muz": "blue",
    "binafsha": "purple", "pushti": "pink", "qizil": "red",
    "jigarrang": "brown", "bej": "beige",
    # --- latin transliterations in uz-locale listings ---
    "cherniy": "black", "chernyi": "black", "beliy": "white", "seriy": "gray",
    "siniy": "blue", "goluboy": "blue", "zeleniy": "green",
    "fioletoviy": "purple", "rozoviy": "pink", "zolotoy": "gold",
    "serebristiy": "silver",
}

# Words that modify a colour but are NOT colours. Never map these.
QUALIFIERS: frozenset[str] = frozenset({
    "velvet", "light", "dark", "golden", "deep", "matte", "glossy",
    "темно", "светло", "небесно", "металлик", "меланж",
    "toq", "och",          # uzbek: dark / light
})


def colors_in_order(tokens: list[str]) -> list[str]:
    """Mapped colours, in the order their words appear."""
    return [COLOR_MAP[t] for t in tokens if t in COLOR_MAP]


def primary_color(tokens: list[str]) -> str | None:
    """The single canonical colour: the LAST mapped token.

    In both English and Russian colour names the base colour comes last
    ("Space Black", "Glacier Blue", "Тёмно-серый"), so the final mapped
    word is the identity and earlier ones are shading.
    """
    found = colors_in_order(tokens)
    return found[-1] if found else None
