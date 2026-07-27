"""SIM configuration. See parsers/uzum.md section 6.

eSIM-only variants sit beside dual-SIM ones at materially lower prices, so
they are a different canonical product, not a colour.
"""
import re

_DUAL = re.compile(r"(nano)?sim\+e-?sim|dualsim|2sim|двесим")
_ESIM = re.compile(r"e-?sim")
_PHYSICAL = re.compile(r"nanosim|nano-sim|\bsim\b")


def is_esim_only(text: str | None) -> bool:
    low = re.sub(r"[\s_.\-]", "", str(text or "").lower())
    if _DUAL.search(low):        # explicit dual markers win, checked first
        return False
    return bool(_ESIM.search(low))


def sim_kind(text: str | None) -> str:
    """One of 'esim_only', 'dual', 'unknown'."""
    if is_esim_only(text):
        return "esim_only"
    low = re.sub(r"[\s_.\-]", "", str(text or "").lower())
    if _DUAL.search(low) or _PHYSICAL.search(low):
        return "dual"
    return "unknown"
