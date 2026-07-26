"""Target-vs-candidate scoring.

Hard reject beats accumulation: a wrong storage can never be out-scored by
matching brand + colour.
"""
from narxnoma.matching.features import Features

ACCEPT_THRESHOLD = 30
HARD_REJECT = -100


def _model_tokens_missing(needed: frozenset[str], other: Features) -> str | None:
    other_tokens = set(other.normalized.split())
    for mt in needed:
        if mt not in other_tokens and mt not in other.normalized:
            return mt
    return None


def score_match(target: Features, cand: Features) -> int:
    score = 0

    if target.brand and cand.brand:
        if target.brand != cand.brand:
            return HARD_REJECT
        score += 10

    if target.storage_gb and cand.storage_gb:
        if target.storage_gb != cand.storage_gb:
            return HARD_REJECT
        score += 20
    elif target.storage_gb and not cand.storage_gb:
        return HARD_REJECT          # kills accessories for free

    # Asymmetric on RAM: a MISSING ram is "unknown, don't reject"; a
    # MISMATCHED ram is a hard reject. Many retailers omit RAM.
    if target.ram_gb and cand.ram_gb:
        if target.ram_gb != cand.ram_gb:
            return HARD_REJECT
        score += 10

    if _model_tokens_missing(target.model_tokens, cand) is not None:
        return HARD_REJECT
    # The reverse direction is what stops "17 Pro Max" matching "17 Pro".
    if _model_tokens_missing(cand.model_tokens, target) is not None:
        return HARD_REJECT
    if target.model_tokens or cand.model_tokens:
        score += 15

    if target.colors:
        if not cand.colors:
            return HARD_REJECT      # unresolvable colour must reject, not pass
        if not (target.colors & cand.colors):
            return HARD_REJECT
        score += 5

    return score


def why(target: Features, cand: Features) -> str:
    """Explain a rejection. Mirrors score_match exactly."""
    if target.brand and cand.brand and target.brand != cand.brand:
        return f"brand {cand.brand}!={target.brand}"
    if target.storage_gb and cand.storage_gb and target.storage_gb != cand.storage_gb:
        return f"storage {cand.storage_gb}!={target.storage_gb}"
    if target.storage_gb and not cand.storage_gb:
        return "cand has NO storage"
    if target.ram_gb and cand.ram_gb and target.ram_gb != cand.ram_gb:
        return f"ram {cand.ram_gb}!={target.ram_gb}"
    missing = _model_tokens_missing(target.model_tokens, cand)
    if missing is not None:
        return f"target token '{missing}' missing"
    extra = _model_tokens_missing(cand.model_tokens, target)
    if extra is not None:
        return f"cand token '{extra}' extra"
    if target.colors and not cand.colors:
        return "cand colour unresolvable"
    if target.colors and cand.colors and not (target.colors & cand.colors):
        return f"colour {sorted(cand.colors)} vs {sorted(target.colors)}"
    return "OK"
