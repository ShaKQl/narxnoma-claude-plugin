from narxnoma.matching.features import extract_features as F
from narxnoma.matching.scoring import ACCEPT_THRESHOLD, HARD_REJECT, score_match, why


def test_exact_match_accepts():
    t = F("Смартфон Honor X9d 12/256 ГБ, черный")
    c = F("Honor X9d 12/256 GB Midnight Black")
    assert score_match(t, c) >= ACCEPT_THRESHOLD


def test_wrong_storage_hard_rejects():
    t = F("Смартфон Honor X9d 12/256 ГБ, черный")
    c = F("Honor X9d 12/512 GB Midnight Black")
    assert score_match(t, c) == HARD_REJECT
    assert "storage" in why(t, c)


def test_wrong_ram_hard_rejects():
    t = F("Смартфон Honor X9d 12/256 ГБ, черный")
    c = F("Honor X9d 8/256 GB Black")
    assert score_match(t, c) == HARD_REJECT
    assert "ram" in why(t, c)


def test_reverse_model_token_check_stops_pro_max_matching_pro():
    # Without this, every Pro request matches the more expensive Pro Max.
    t = F("Смартфон Apple iPhone 17 Pro 256 ГБ, Silver")
    c = F("Смартфон Apple iPhone 17 Pro Max 256 ГБ, Silver")
    assert score_match(t, c) == HARD_REJECT
    assert "max" in why(t, c)


def test_iphone_16_does_not_match_iphone_air():
    # The 1.44M bug: an iPhone 16 at 12,000,000 matched an iPhone Air target.
    t = F("Смартфон Apple iPhone Air 256 ГБ, Space Black")
    c = F("Apple iPhone 16 256 GB Black")
    assert score_match(t, c) == HARD_REJECT


def test_iphone_16_pro_does_not_match_iphone_17_pro():
    t = F("Смартфон Apple iPhone 17 Pro 256 ГБ, Silver")
    c = F("Apple iPhone 16 Pro 256 GB Silver")
    assert score_match(t, c) == HARD_REJECT


def test_accessory_without_storage_rejects():
    # Target has storage, candidate has none -> accessory. Free filter.
    t = F("Смартфон Honor X9d 12/256 ГБ, черный")
    c = F("Чехол для Honor X9d черный")
    assert score_match(t, c) == HARD_REJECT
    assert "NO storage" in why(t, c)


def test_missing_ram_on_candidate_is_allowed():
    # Many retailers omit RAM; a MISSING ram must not reject, only a wrong one.
    t = F("Смартфон Honor X9d 12/256 ГБ, черный")
    c = F("Honor X9d 256GB Black")
    assert score_match(t, c) >= ACCEPT_THRESHOLD


def test_colour_mismatch_rejects():
    t = F("Смартфон Honor X9d 12/256 ГБ, черный")
    c = F("Honor X9d 12/256 GB Desert Gold")
    assert score_match(t, c) == HARD_REJECT
    assert "colour" in why(t, c)


def test_candidate_with_no_resolvable_colour_rejects():
    # Dropping the colour check would make it a wildcard: "Конфетный" and
    # "Хром" matched BOTH Awesome Gray and Awesome Navy simultaneously.
    t = F("Смартфон Honor X9d 12/256 ГБ, черный")
    c = F("Honor X9d 12/256 GB Конфетный")
    assert score_match(t, c) == HARD_REJECT


def test_why_returns_ok_for_a_match():
    t = F("Смартфон Honor X9d 12/256 ГБ, черный")
    c = F("Honor X9d 12/256 GB Midnight Black")
    assert why(t, c) == "OK"


def test_target_without_storage_rejects_candidate_that_states_storage():
    # Symmetric to the accessory case. A storage-less target used to score
    # exactly 30 (brand 10 + model 15 + colour 5) -- the accept threshold --
    # against a candidate of ANY capacity, so one target accepted both a
    # 256 GB and a 1 TB listing and pooled their prices into one median.
    t = F("iPhone 17 Pro Black")
    assert t.storage_gb is None
    for c in [F("Apple iPhone 17 Pro 256GB Black"), F("Apple iPhone 17 Pro 1TB Black")]:
        assert score_match(t, c) == HARD_REJECT
        assert "target has NO storage" in why(t, c)


def test_missing_ram_stays_asymmetric():
    # RAM and storage are deliberately different: a target with no RAM must
    # still accept a candidate that states one, or every retailer that prints
    # RAM would be rejected by a target that does not.
    t = F("Honor X9d 256GB Black")
    c = F("Смартфон Honor X9d 12/256 ГБ, черный")
    assert t.ram_gb is None and c.ram_gb == 12
    assert score_match(t, c) >= ACCEPT_THRESHOLD


def test_model_token_must_match_a_whole_word():
    # The fallback was a raw substring test against the candidate's
    # normalised name, so the token "6" was satisfied by the "16" in
    # "iPhone 16" -- an iPhone 6 target accepted an iPhone 16 listing.
    t = F("Apple iPhone 6 128GB Black")
    c = F("Apple iPhone 16 128GB Black")
    assert score_match(t, c) == HARD_REJECT
