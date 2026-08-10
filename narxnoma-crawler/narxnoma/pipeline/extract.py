"""Stage 2: an offer row -> the identity Plan 1's matcher can reason about.

This stage is deliberately **thin and pure**. A row goes in, a structure comes
out; there is no I/O and no judgement here. Every decision about what makes two
listings the same product lives in `narxnoma.matching`, and keeping that true is
what lets Task 4's clustering be tested without a database.
"""
from dataclasses import dataclass
from typing import Any, Mapping

from narxnoma.matching import (
    Features,
    PartialKey,
    VariantKey,
    extract_features,
    partial_key,
    sim_kind,
    variant_key,
)

# Characteristic keys, across retailers and their typos, that carry SIM
# configuration. uzum states this in structured data that never reaches the
# product name, so a name-only reading would classify a dual-SIM phone as
# "unknown" and let it cluster with the eSIM-only variant -- a different
# product at a materially different price. See docs/parsers/uzum.md section 6.
_SIM_CHARACTERISTIC_PREFIXES = ("sim", "сим", "сим-карта")


@dataclass(frozen=True)
class OfferIdentity:
    """What one offer claims to be.

    `key` is set only when every identity field is known. When it is None,
    `partial` carries whatever *was* known, so clustering can try to resolve it
    against existing variants -- and refuse when more than one fits.
    """

    offer_id: Any
    features: Features
    sim_kind: str
    key: VariantKey | None
    partial: PartialKey


def _sim_text_from_raw(raw: Mapping[str, Any] | None) -> str | None:
    """Pull an explicit SIM statement out of source-specific payload.

    Returns None when the payload says nothing about SIM, so the caller falls
    back to the product name rather than treating silence as a signal.
    """
    if not raw:
        return None

    values = raw.get("characteristic_values")
    if isinstance(values, list):
        for entry in values:
            if not isinstance(entry, Mapping):
                continue
            characteristic = entry.get("characteristic")
            title = ""
            if isinstance(characteristic, Mapping):
                title = str(characteristic.get("title") or "")
            key = title.strip().casefold()
            if key.startswith(_SIM_CHARACTERISTIC_PREFIXES):
                value = str(entry.get("title") or "").strip()
                if value:
                    return value

    # A source may also state it flatly.
    for field in ("sim", "sim_type", "sim_kind"):
        value = raw.get(field)
        if value:
            return str(value)
    return None


def identify(offer_row: Mapping[str, Any]) -> OfferIdentity:
    """Turn one offer row into its canonical identity, or as much as is known.

    `offer_row` needs `id` and `name_raw`; `raw` is optional source-specific
    payload, used only for a SIM signal the name cannot carry.
    """
    name_raw = offer_row.get("name_raw") or ""
    features = extract_features(name_raw)

    # An explicit statement beats an inference. A name that merely omits "eSIM"
    # is silent, not evidence of a dual-SIM device.
    sim_text = _sim_text_from_raw(offer_row.get("raw"))
    kind = sim_kind(sim_text) if sim_text else sim_kind(name_raw)

    # The category the offer was harvested under (Plan 5). Defaults to
    # smartphones for offers written before the column existed.
    category = offer_row.get("category") or "smartphones"

    return OfferIdentity(
        offer_id=offer_row.get("id"),
        features=features,
        sim_kind=kind,
        key=variant_key(features, kind, category),
        partial=partial_key(features, kind, category),
    )
