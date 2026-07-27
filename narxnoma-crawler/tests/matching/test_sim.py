from narxnoma.matching.sim import is_esim_only, sim_kind


def test_explicit_dual_markers_are_not_esim_only():
    # Checked FIRST: "SIM+eSIM" contains "esim" but is the physical variant.
    for s in ["SIM+eSIM", "nanoSim+eSim", "2 SIM", "dualSIM", "две сим"]:
        assert is_esim_only(s) is False


def test_esim_only_forms():
    # uzum encodes it three ways; all must be screened. Price gap is real:
    # 20,789,010 dual vs 18,099,000 eSIM-only for the same nominal phone.
    for s in ["17 Pro Max 256 (e-Sim)", "iPhone 17 Pro Max 256GB (eSIM)",
              "Apple iPhone 17 Air 256GB, eSIM"]:
        assert is_esim_only(s) is True


def test_no_sim_information():
    assert is_esim_only("Honor X9d 12/256 GB Black") is False


def test_sim_kind_labels():
    assert sim_kind("iPhone 17 Pro 256GB (eSIM)") == "esim_only"
    assert sim_kind("iPhone 17 Pro 256GB nanoSIM+eSIM") == "dual"
    assert sim_kind("Honor X9d 12/256 GB Black") == "unknown"


def test_slash_separated_dual_marker_is_not_esim_only():
    # docs/parsers/uzum.md §6: the rendered spec sheet for the dual variant
    # shows "Тип SIM карты : nano-SIM/eSIM" -- a slash, not a plus. Before the
    # fix this collapsed to "...nanosim/esim" with no "+", so _DUAL missed it
    # and _ESIM matched the trailing "esim", misclassifying a dual phone as
    # eSIM-only.
    s = "Тип SIM карты : nano-SIM/eSIM"
    assert is_esim_only(s) is False
    assert sim_kind(s) == "dual"


def test_sim_word_boundary_before_cyrillic():
    # "SIM карта" (uzum.md §6, the SIM characteristic key/value form).
    # Separator-stripping turns it into "simкарта"; Cyrillic "к" is a \w
    # character under Python's Unicode-aware \b, so \bsim\b never matched
    # and sim_kind fell through to "unknown" instead of "dual".
    assert sim_kind("SIM карта") == "dual"


def test_slash_separated_dual_marker_esim_only_false():
    # Same slash-separated marker as above, in its shorter raw form.
    assert is_esim_only("nanoSIM/eSIM") is False


def test_genuine_esim_only_still_detected():
    # Pins that widening separator stripping does not over-correct and start
    # calling genuine eSIM-only phones dual.
    s = "iPhone 17 Pro Max 256GB (eSIM)"
    assert is_esim_only(s) is True
    assert sim_kind(s) == "esim_only"


def test_no_sim_information_with_a_slash_in_the_name():
    # A name with no SIM information at all, that also contains a slash in
    # the memory figure -- proves widened separator stripping ("/" now
    # stripped too) does not create a spurious "simesim"/"esim" match.
    assert sim_kind("Honor X9d 12/256 GB Black") == "unknown"
