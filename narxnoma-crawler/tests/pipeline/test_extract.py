"""The extract stage is pure: a row in, an identity out. No database here."""
from narxnoma.pipeline.extract import OfferIdentity, identify


def row(name, raw=None, offer_id="off-1"):
    return {"id": offer_id, "name_raw": name, "raw": raw}


def test_complete_name_yields_a_full_key():
    ident = identify(row("Смартфон Honor X9d 12/256 ГБ, черный"))
    assert isinstance(ident, OfferIdentity)
    assert ident.key is not None
    assert ident.key.brand == "honor"
    assert ident.key.ram_gb == 12 and ident.key.storage_gb == 256
    assert ident.key.color == "black"


def test_missing_ram_on_a_non_apple_brand_yields_no_key_but_a_usable_partial():
    # Samsung publishes RAM, so a listing that omits it is genuinely
    # under-specified -- we cannot know which variant it is.
    ident = identify(row("Samsung Galaxy A17 128GB Blue"))
    assert ident.key is None
    assert ident.partial.brand == "samsung"
    assert ident.partial.storage_gb == 128
    assert ident.partial.ram_gb is None
    assert ident.partial.color == "blue"


def test_apple_without_ram_still_yields_a_full_key():
    # Apple never publishes RAM. Requiring it would make every iPhone
    # permanently unkeyable, which is the opposite of what we want.
    ident = identify(row("Смартфон Apple iPhone 17 Pro 256 ГБ, Silver"))
    assert ident.key is not None
    assert ident.key.ram_gb is None
    assert ident.key.storage_gb == 256


def test_unmappable_colour_yields_no_key():
    # Colour is a hard identity field: a colour we cannot resolve is not the
    # same as no colour, and must never be treated as a wildcard.
    ident = identify(row("Смартфон Redmi Note 15 8/256 ГБ Конфетный"))
    assert ident.key is None
    assert ident.partial.color is None


def test_explicit_sim_signal_in_raw_beats_the_name():
    # uzum states SIM configuration in structured characteristics that never
    # reach the product name. Reading only the name would call this dual-SIM
    # phone "unknown" and let it cluster with the eSIM-only variant, which is a
    # different product at a materially different price.
    name = "Смартфон Apple iPhone 17 Pro 256 ГБ, Silver"
    raw = {"characteristic_values": [
        {"title": "e-SIM", "characteristic": {"title": "Сим-карта"}},
    ]}
    from_name = identify(row(name))
    from_raw = identify(row(name, raw=raw))
    assert from_name.sim_kind == "unknown"
    assert from_raw.sim_kind == "esim_only"
    # And the difference must reach the key, not stop at the report.
    assert from_name.key != from_raw.key


def test_dual_sim_characteristic_is_read_as_dual():
    raw = {"characteristic_values": [
        {"title": "nano-SIM/eSIM", "characteristic": {"title": "SIM карта"}},
    ]}
    ident = identify(row("Смартфон Honor X9d 12/256 ГБ, черный", raw=raw))
    assert ident.sim_kind == "dual"


def test_silent_payload_falls_back_to_the_name():
    # A payload that says nothing about SIM is silence, not evidence.
    raw = {"characteristic_values": [
        {"title": "Qora", "characteristic": {"title": "Rangi"}},
    ]}
    ident = identify(row("iPhone 17 Pro Max 256GB (eSIM)", raw=raw))
    assert ident.sim_kind == "esim_only"


def test_malformed_raw_does_not_raise():
    # raw comes straight from parsed retailer JSON; it is not trustworthy.
    for bad in (None, {}, {"characteristic_values": None},
                {"characteristic_values": ["not-a-dict"]},
                {"characteristic_values": [{"characteristic": "not-a-dict"}]}):
        ident = identify(row("Смартфон Honor X9d 12/256 ГБ, черный", raw=bad))
        assert ident.key is not None


def test_offer_id_is_carried_through():
    assert identify(row("Смартфон Honor X9d 12/256 ГБ, черный",
                        offer_id="abc-123")).offer_id == "abc-123"


def test_extract_stage_does_no_io():
    import inspect

    import narxnoma.pipeline.extract as mod

    source = inspect.getsource(mod)
    for forbidden in ("psycopg", "requests", "open(", "connect("):
        assert forbidden not in source, f"{forbidden} in a stage that must stay pure"
