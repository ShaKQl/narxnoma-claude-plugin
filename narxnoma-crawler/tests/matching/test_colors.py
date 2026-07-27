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


def test_graphite_is_gray_not_black():
    # Corpus: "Redmi Pad Pro 6/128 Graphite Gray", "Galaxy A56 5G 8/256 GB
    # Graphite". While graphite mapped to black, "Graphite Gray" produced
    # {black, gray} and falsely intersected genuine Black listings.
    resolved = set(colors_in_order(["graphite", "gray"]))
    assert "black" not in resolved
    assert resolved == {"gray"}
    assert primary_color(["graphite", "gray"]) == "gray"


def test_cobalt_is_a_qualifier_not_blue_or_purple():
    # Corpus: all 17 occurrences are the compound "Cobalt Violet" (Galaxy
    # S26 family); cobalt never appears standalone. Remapping it to blue
    # (as one review suggested) would yield {blue, purple} and false-match
    # Blue listings, so it must be a qualifier, not a colour.
    resolved = set(colors_in_order(["cobalt", "violet"]))
    assert "blue" not in resolved
    assert resolved == {"purple"}
    assert "cobalt" in QUALIFIERS
    assert "cobalt" not in COLOR_MAP


def test_zolotistiy_maps_but_golden_does_not():
    # Corpus: all 10 occurrences of "золотистый" are standalone ("Honor X9D
    # 12/256 GB, золотистый"), while all 7 occurrences of "golden" are
    # compounds ("Golden White", "Golden Black"). The two are deliberately
    # classified differently: золотистый is a base colour, golden is a
    # shading qualifier.
    assert COLOR_MAP["золотистый"] == "gold"
    assert "golden" not in COLOR_MAP
    assert "golden" in QUALIFIERS


def test_qualifiers_and_color_map_are_disjoint():
    # Invariant, not a spot check. A word in both would be mapped to a colour
    # by colors_in_order AND skipped as a qualifier by feature extraction, so
    # "Velvet Grey"-style compounds would resolve to two colours and falsely
    # intersect a listing of the shading word's colour.
    overlap = set(QUALIFIERS) & set(COLOR_MAP)
    assert not overlap, f"words classified both ways: {sorted(overlap)}"
