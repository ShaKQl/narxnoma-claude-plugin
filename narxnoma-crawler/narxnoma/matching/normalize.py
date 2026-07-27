"""String normalisation. See parsers/_matching-engine.md section 1."""
import re

_REPLACEMENTS = [
    ("–", "-"), ("—", "-"),   # en dash, em dash
    (",", " "), ("/", " "), ("|", " "),
    ("ё", "е"),               # ё -> е
]


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
    return re.sub(r"\s+", " ", t).strip()
