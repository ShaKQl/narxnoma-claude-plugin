from narxnoma.matching import features as features_module
from narxnoma.matching.features import Features, extract_features


def test_brand_aliases():
    assert extract_features("iPhone 17 Pro 256GB").brand == "apple"
    assert extract_features("Redmi Note 15 8/256").brand == "xiaomi"
    assert extract_features("POCO X8 Pro 8/256").brand == "xiaomi"
    assert extract_features("Honor X9d 12/256").brand == "honor"


def test_model_tokens_keep_model_numbers():
    f = extract_features("Смартфон Samsung Galaxy A17 6/128 ГБ, чёрный")
    assert "a17" in f.model_tokens
    assert f.ram_gb == 6 and f.storage_gb == 128
    assert f.primary_color == "black"


def test_air_fe_se_are_model_modifiers():
    # Without "air", an iPhone Air target carries NO model token at all,
    # and matches every other iPhone.
    assert "air" in extract_features("Apple iPhone Air 256 ГБ, Space Black").model_tokens
    assert "fe" in extract_features("Samsung Galaxy S25 FE 8/128 Navy").model_tokens


def test_pro_and_max_are_both_kept():
    f = extract_features("iPhone 17 Pro Max 256 ГБ, Silver")
    assert {"pro", "max"} <= f.model_tokens


def test_sku_codes_are_not_model_tokens():
    # idea appends part numbers ("SM-A376EZADSOZ"); mediapark lists
    # "SAMSUNG SM-A075F A07". Real designators are <= 4 chars.
    f = extract_features("SAMSUNG SM-A075F A07 4/64")
    assert "a07" in f.model_tokens
    assert not any(len(t) >= 5 and any(c.isdigit() for c in t) for t in f.model_tokens)


def test_sku_min_len_is_measured_not_guessed():
    """Pin the threshold at 5, because raising it measurably hurts.

    Across all 14,860 golden rows, accept/reject agreement is 99.993% at 5 and
    99.987% at 6, 7, 8 and with the rule disabled entirely. Raising it is
    strictly worse, and the reason is visible in the two assertions below: at 6,
    five-character spec fragments survive as model tokens and then reject
    otherwise-valid candidates that simply do not repeat the marketing blurb.

    If you are here because you want to rescue "reno15" or "magic8", changing
    this number is not the fix -- see test_known_gap_real_designators_of_five_plus.
    """
    assert features_module._SKU_MIN_LEN == 5


def test_spec_blurb_fragments_never_become_model_tokens():
    # uzum card titles are marketing copy: '6.7" AMOLED 120Hz, 200Мп, 6500 мАч'.
    # If any of these became a model token, every candidate that omitted the
    # blurb -- which is most of them -- would be rejected for "missing" it.
    f = extract_features("Смартфон Xiaomi Redmi Note 15 Pro 8/256 120Hz 200MP 6500mAh, чёрный")
    for junk in ("120hz", "200mp", "6500mah"):
        assert junk not in f.model_tokens
    assert {"15", "note", "pro", "redmi"} <= f.model_tokens


def test_short_designators_still_survive():
    # The rule must not become so aggressive that it eats identity. These are
    # the tokens the whole matcher keys on.
    for name, token in [
        ("Samsung Galaxy A17 6/128 Black", "a17"),
        ("Honor X9d 12/256 Black", "x9d"),
        ("Samsung Galaxy S26 Ultra 12/256 Black", "s26"),
        ("Vivo Y31d 4/128 Black", "y31d"),
    ]:
        assert token in extract_features(name).model_tokens, name


def test_known_gap_real_designators_of_five_plus():
    """Document, rather than hide, what this rule costs.

    Length cannot separate real designators from catalogue codes -- they
    overlap. In the corpus, length 5 holds both 'fold4'/'pro12' and
    '120hz'/'200mp'; length 6 holds both 'magic8' and 'mg3730'/'bt7510'.

    So these products are currently unkeyable, and that is a real gap, not a
    detail. Fixing it needs a targeted designator allowlist applied BEFORE the
    SKU rule, plus OPPO and Honor fixtures to measure against -- the golden
    corpus contains zero 'reno*' tokens and only 26 OPPO rows, so there is
    nothing here to tune with. This test exists so the gap fails loudly the day
    someone adds that allowlist, rather than lingering undocumented.
    """
    for name, lost in [
        ("OPPO Reno15 5G 12/512GB Aurora White", "reno15"),
        ("Honor Magic8 Pro 12/512 Black", "magic8"),
    ]:
        assert lost not in extract_features(name).model_tokens, (
            f"{lost!r} is now kept -- if that was deliberate, update this test "
            f"and re-measure agreement across the golden corpus"
        )


def test_galaxy_is_not_required():
    # mediapark lists the A07 with no "Galaxy" at all.
    assert "galaxy" not in extract_features("Samsung Galaxy A17 6/128").model_tokens


def test_memory_figures_never_become_model_tokens():
    f = extract_features("Honor X9d 12/256 GB Black")
    assert "12" not in f.model_tokens
    assert "256" not in f.model_tokens


def test_bands_are_reserved_not_model_tokens():
    f = extract_features("Samsung Galaxy A27 5G 8/256 ГБ, Черный")
    assert "5g" not in f.model_tokens


def test_unmappable_colour_yields_no_colour():
    # "Конфетный" is not in COLOR_MAP, so no colour resolves. score_match
    # then hard-rejects it for any colour-bearing target rather than letting
    # it act as a wildcard.
    f = extract_features("Смартфон Redmi 15 8/256 Конфетный")
    assert f.primary_color is None
    assert f.colors == frozenset()


def test_qualifier_does_not_hide_the_base_colour():
    # "Velvet Grey": 'velvet' is a QUALIFIER and must not map, but 'grey' must.
    g = extract_features("Смартфон Honor X8D 8/256 Velvet Grey")
    assert g.primary_color == "gray"


def test_features_are_hashable_and_frozen():
    f = extract_features("Honor X9d 12/256 GB Black")
    assert isinstance(f, Features)
    hash(f)
