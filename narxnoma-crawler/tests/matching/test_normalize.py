from narxnoma.matching.normalize import normalize


def test_lowercases_and_collapses_whitespace():
    assert normalize("  Samsung   Galaxy  A17 ") == "samsung galaxy a17"


def test_none_and_empty():
    assert normalize(None) == ""
    assert normalize("") == ""


def test_folds_yo_to_ye():
    # uzum ships both "Тёмно-зелёный" and "Темно-зеленый" for the same colour
    assert normalize("Тёмно-зелёный") == "темно зеленый"


def test_separators_become_spaces():
    assert normalize("8ГБ/256ГБ") == "8гб 256гб"
    assert normalize("Honor X9d, Midnight Black, 12/256 GB") == \
        "honor x9d midnight black 12 256 gb"


def test_trailing_plus_becomes_plus_word():
    # "Pro+" is a real model modifier
    assert normalize("Honor X5d Pro+") == "honor x5d pro plus"


def test_inner_plus_becomes_space_not_plus_word():
    # THE BUG: mapping every '+' to 'plus' injected a phantom model token
    # that rejected every iPhone on BeeMarket.
    assert normalize("SIM+eSIM") == "sim esim"
    assert "plus" not in normalize("nanoSim+eSim")
