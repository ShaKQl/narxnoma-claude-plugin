"""SIM configuration. See parsers/uzum.md section 6.

eSIM-only variants sit beside dual-SIM ones at materially lower prices, so
they are a different canonical product, not a colour.
"""
import re

# Pair separators, widened to include "/" and "+": the rendered dual-variant
# spec sheet reads "nano-SIM/eSIM" (a slash, not a plus), and the raw
# characteristic value is "SIM+eSIM". Stripping all of \s _ . - / + collapses
# every documented spelling onto one canonical form before matching, so a
# single pair of regexes covers "SIM+eSIM", "nanoSim+eSim" and
# "nano-SIM/eSIM" alike.
_SEPARATORS = re.compile(r"[\s_.\-/+]")
_DUAL = re.compile(r"simesim|dualsim|2sim|двесим")
_ESIM = re.compile(r"esim")


def is_esim_only(text: str | None) -> bool:
    low = _SEPARATORS.sub("", str(text or "").lower())
    if _DUAL.search(low):        # explicit dual markers win, checked first
        return False
    return bool(_ESIM.search(low))


def sim_kind(text: str | None) -> str:
    """One of 'esim_only', 'dual', 'unknown'."""
    if is_esim_only(text):
        return "esim_only"
    low = _SEPARATORS.sub("", str(text or "").lower())
    if _DUAL.search(low):
        return "dual"
    # Any remaining mention of a SIM at this point (eSIM-only and dual have
    # both been ruled out) is a physical one. Separator-stripping merges
    # "SIM карта" into "simкарта", where \bsim\b no longer matches because
    # Cyrillic к is a \w character under Python's Unicode-aware \b — so a
    # plain substring test replaces the old _PHYSICAL regex entirely.
    if "sim" in low:
        return "dual"
    return "unknown"
