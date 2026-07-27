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
