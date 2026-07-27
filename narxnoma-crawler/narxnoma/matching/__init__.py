"""Pure matching engine: raw retailer name -> canonical variant identity.

This package must never import anything outside the standard library.
"""
from narxnoma.matching.colors import COLOR_MAP, QUALIFIERS, primary_color
from narxnoma.matching.features import Features, extract_features
from narxnoma.matching.keys import (
    PartialKey, VariantKey, display_name, ordered_model_tokens, partial_key,
    resolve_partial, slug, variant_key,
)
from narxnoma.matching.normalize import normalize
from narxnoma.matching.scoring import ACCEPT_THRESHOLD, HARD_REJECT, score_match, why
from narxnoma.matching.sim import is_esim_only, sim_kind
from narxnoma.matching.stats import robust_median

__all__ = [
    "ACCEPT_THRESHOLD", "COLOR_MAP", "Features", "HARD_REJECT", "PartialKey",
    "QUALIFIERS", "VariantKey", "display_name", "extract_features",
    "is_esim_only", "normalize", "ordered_model_tokens", "partial_key",
    "primary_color", "resolve_partial", "robust_median", "score_match",
    "sim_kind", "slug", "variant_key", "why",
]
