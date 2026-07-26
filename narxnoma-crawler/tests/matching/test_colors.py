from narxnoma.matching.colors import COLOR_MAP, QUALIFIERS, colors_in_order, primary_color


def test_english_base_words():
    assert colors_in_order(["midnight", "black"]) == ["black", "black"]
    assert primary_color(["glacier", "blue"]) == "blue"


def test_primary_colour_is_the_last_mapped_token():
    # "Space Black" -> {gray, black}; the base colour is the final word.
    assert primary_color(["space", "black"]) == "black"
    assert primary_color(["desert", "gold"]) == "gold"


def test_russian_vocabulary():
    assert primary_color(["темно", "серый"]) == "gray"
    assert primary_color(["серебряный"]) == "silver"


def test_uzbek_vocabulary():
    # uzum serves uz-language card/model strings; unresolvable colours reject,
    # so every missing word here was a silent miss. See parsers/uzum.md section 8.
    assert primary_color(["kumush"]) == "silver"
    assert primary_color(["tilla"]) == "gold"
    assert primary_color(["yashil"]) == "green"
    assert primary_color(["muz"]) == "blue"
    assert primary_color(["qora"]) == "black"


def test_qualifiers_are_never_colours():
    # "Velvet Grey" -> {black, gray} would pool Black sellers into a Grey median.
    for q in ["velvet", "light", "dark", "golden", "темно", "светло", "меланж"]:
        assert q not in COLOR_MAP, f"{q} must not map to a colour"
        assert q in QUALIFIERS


def test_rang_is_not_a_colour():
    # Uzbek "Kumush rang" = "silver colour"; 'rang' is the word "colour".
    assert "rang" not in COLOR_MAP


def test_no_colour_returns_none():
    assert primary_color(["samsung", "galaxy"]) is None
    assert colors_in_order(["samsung"]) == []
