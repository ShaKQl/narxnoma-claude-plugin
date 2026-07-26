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
