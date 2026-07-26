"""RAM and storage extraction.

The lookbehind (?<![a-zа-я\\d]) before each figure is what stops a model
code being read as memory. See docs/parsers/_matching-engine.md.
"""
import re

from narxnoma.matching.brands import BRANDS_WITHOUT_PUBLISHED_RAM

_UNIT = re.compile(r"(?<![a-zа-я\d])(\d{1,4})\s*(gb|гб|tb|тб)\b")
_STORAGE_PAIR = re.compile(r"(?<![a-zа-я\d])(\d{1,3})\s+(\d{2,4})(?!\d)")
_RAM_PAIR = re.compile(r"(?<![a-zа-я\d])(\d{1,2})\s+(\d{2,4})(?!\d)")
_PAIR_SEPARATOR = re.compile(r"\d\s*[/\\+|]\s*\d")

_MAX_PLAUSIBLE_RAM = 24


def extract_memory(
    raw: str | None, normalized: str, brand: str | None
) -> tuple[int | None, int | None]:
    """Return (ram_gb, storage_gb). Either may be None."""
    ram: int | None = None
    storage: int | None = None

    # Collect ALL unit-bearing figures. Sellers write "8ГБ/256ГБ", where a
    # single-match regex reads the RAM as the storage.
    units: list[int] = []
    for m in _UNIT.finditer(normalized):
        val = int(m.group(1))
        if m.group(2) in ("tb", "тб"):
            val *= 1024
        units.append(val)

    if len(units) >= 2:
        storage = max(units)
        if min(units) <= _MAX_PLAUSIBLE_RAM:
            ram = min(units)
    elif len(units) == 1:
        if units[0] >= 32:
            storage = units[0]
        else:
            ram = units[0]

    if storage is None:                      # bare "6 128" form
        for m in _STORAGE_PAIR.finditer(normalized):
            a, b = int(m.group(1)), int(m.group(2))
            if max(a, b) >= 32:
                storage = max(a, b)
                break

    # A bare "12 256" pair normally means RAM/storage -- but "iPhone 16 256 GB"
    # has the identical shape, and reading 16 as RAM deletes the model number
    # from model_tokens, making iPhone 16 / 17 / Air interchangeable.
    # normalize() has already erased the "/" that tells them apart, so test the
    # RAW string, and never infer RAM for Apple (which does not publish it).
    has_separator = bool(_PAIR_SEPARATOR.search(str(raw or "")))
    if ram is None and (has_separator or brand not in BRANDS_WITHOUT_PUBLISHED_RAM):
        for m in _RAM_PAIR.finditer(normalized):
            a, b = int(m.group(1)), int(m.group(2))
            if min(a, b) <= _MAX_PLAUSIBLE_RAM and max(a, b) >= 32:
                ram = min(a, b)
                break

    return ram, storage
