"""String normalisation. See parsers/_matching-engine.md section 1."""
import re

_REPLACEMENTS = [
    ("–", "-"), ("—", "-"),   # en dash, em dash
    (",", " "), ("/", " "), ("|", " "),
    ("ё", "е"),               # ё -> е
]

# Latin/Cyrillic lookalikes. Retailers really do mix the two scripts inside one
# word, and the two spellings are visually identical, so nothing downstream can
# tell them apart -- they simply become two products.
#
# MEASURED on the live catalogue: "Tелевизор Artel A32PHB100" (Latin T),
# "Cтиральная машина Bosch" (Latin C), "Стиральная машинa" and "Газовые плитa"
# (Latin a), and "Автохолодильник Alpicool С20" (CYRILLIC С inside a model
# code, where every other listing writes a Latin C). The project ledger already
# recorded uzum shipping "Cмартфон" with a Latin C for the same reason.
#
# Keyed by the LOWERCASE form, because normalize() lowercases first: an
# uppercase Latin T has already become "t" by the time this runs.
_LAT_TO_CYR = str.maketrans("abcehkmoptxy", "авсенкмортху")
_CYR_TO_LAT = str.maketrans("авсенкмортху", "abcehkmoptxy")

_HAS_CYR = re.compile(r"[а-я]")
_HAS_LAT = re.compile(r"[a-z]")
_HAS_DIGIT = re.compile(r"\d")


def _fold_homoglyphs(token: str) -> str:
    """Force one script per token, so two spellings cannot become two products.

    Which script wins depends on what the token IS, because the two populations
    pull opposite ways:

    - a token carrying a DIGIT is a model code ("с20", "a32phch010"), and model
      codes are Latin. Folding Cyrillic -> Latin makes "С20" and "C20" one code.
    - a token of letters only is a Russian word ("машинa", "tелевизор"), so the
      stray Latin character folds INTO Cyrillic.

    A token already written in one script is left completely alone: the
    translation only fires when both scripts are present, which is the only
    situation where one of them must be a typo.
    """
    cyr = len(_HAS_CYR.findall(token))
    lat = len(_HAS_LAT.findall(token))
    if not cyr:
        return token
    # A token carrying a digit is a model code, and model codes are Latin --
    # even when EVERY letter in it was typed in Cyrillic ("Alpicool С20").
    if _HAS_DIGIT.search(token):
        return token.translate(_CYR_TO_LAT)
    if not lat:
        return token
    # Letters only, both scripts: the minority script is the typo. Measured
    # case that forces this to be a majority test rather than a fixed
    # direction -- "PRЕMIER" is a Latin brand containing one Cyrillic Е, so
    # folding Latin->Cyrillic produced the unmatchable "рrемiеr" and lost the
    # brand entirely, while "машинa" is a Cyrillic word with one Latin a.
    return token.translate(_CYR_TO_LAT if lat > cyr else _LAT_TO_CYR)


def normalize(s: str | None) -> str:
    """Lowercase, fold separators, strip punctuation, collapse whitespace."""
    if not s:
        return ""
    t = str(s).lower().strip()
    for a, b in _REPLACEMENTS:
        t = t.replace(a, b)
    # '+' becomes ' plus ' ONLY as a trailing model marker (e.g. "Pro+").
    # A '+' inside "SIM+eSIM" is followed by a letter, so it becomes a space.
    t = re.sub(r"\+(?=\s|$)", " plus ", t)
    t = t.replace("+", " ")
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    # Per token, after splitting: a mixed-script token is a typo in one script
    # or the other, and the two spellings are indistinguishable to a reader.
    return " ".join(_fold_homoglyphs(tok) for tok in t.split())
