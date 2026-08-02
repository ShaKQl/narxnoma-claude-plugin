"""RAM and storage extraction.

The lookbehind (?<![a-zа-я\\d]) before each figure is what stops a model
code being read as memory. See docs/parsers/_matching-engine.md.
"""
import re

from narxnoma.matching.brands import BRANDS_WITHOUT_PUBLISHED_RAM

_UNIT = re.compile(r"(?<![a-zа-я\d])(\d{1,4})\s*(gb|гб|tb|тб)\b")

# Zero-width: the two figures are captured inside a lookahead instead of
# being consumed, so re.finditer's matches can overlap. A plain consuming
# regex can only offer non-overlapping candidates, and a model number
# directly adjacent to RAM ("Redmi Note 15 12/256" normalises to
# "redmi note 15 12 256") makes the model+RAM pair ("15", "12") match
# first, consuming "12" and hiding the real memory pair ("12", "256") from
# ever being scanned. Matching zero-width lets the scan advance one
# character at a time and consider "12 256" too, so the plausibility check
# below can reject "15 12" and still go on to find the real pair.
_STORAGE_PAIR = re.compile(r"(?<![a-zа-я\d])(?=(\d{1,3})\s+(\d{2,4})(?!\d))")
_RAM_PAIR = re.compile(r"(?<![a-zа-я\d])(?=(\d{1,2})\s+(\d{2,4})(?!\d))")
_PAIR_SEPARATOR = re.compile(r"\d\s*[/\\+|]\s*\d")

_MAX_PLAUSIBLE_RAM = 24

# Plausible RAM/storage sizes for the bare-pair fallbacks ("12 256" with no
# unit and no separator). A model number like the "7" in "Galaxy Z Fold 7
# 512 ГБ" or the "5" in "Galaxy Watch 5 44mm" has the same shape as a real
# memory pair; restricting candidates to values retailers actually sell
# stops the model number from being absorbed as RAM or storage.
_PLAUSIBLE_RAM_GB = frozenset({1, 2, 3, 4, 6, 8, 10, 12, 16, 18, 24})
_PLAUSIBLE_STORAGE_GB = frozenset({32, 64, 128, 256, 512, 1024, 2048})

# Last-resort: a storage figure standing entirely alone, with neither a unit
# nor a second adjacent figure. Every rule above needs one or the other, so
# "Apple iPhone 12 pro 128 Синий" read as no memory at all and the listing
# became unkeyable -- while "Apple iPhone 12 128 Алый" read 128 correctly,
# purely because the model number happened to sit next to the capacity.
#
# The shape is common rather than exotic: uzum states memory in a per-SKU
# characteristic whose value is often the bare figure (Память: "128"), and
# that value reaches the name with nothing beside it.
_LONE_FIGURE = re.compile(r"(?<![a-zа-я\d])(\d{2,4})(?!\d)")

# A lone figure is much weaker evidence than a pair, so it needs screening a
# pair does not: these units mark a figure as something else entirely, and
# 64 (МП), 128 (mp) and 512 are all plausible capacities sitting in blurbs.
_OTHER_UNIT = re.compile(
    r"^\s*(mp|мп|mah|мач|hz|гц|mm|мм|w|вт|nm|нм|dpi|ppi|fps|core|ядер)\b"
)


def scan_memory(
    raw: str | None, normalized: str, brand: str | None
) -> tuple[int | None, int | None, int | None]:
    """Return (ram_gb, storage_gb, stated_ram_gb).

    ``stated_ram_gb`` is the RAM figure a retailer actually wrote, BEFORE the
    Apple suppression below removes it from identity. Callers that build model
    tokens need it: a suppressed figure is still a memory figure, and must not
    be allowed to fall through and become a model token instead.
    """
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
            if max(a, b) not in _PLAUSIBLE_STORAGE_GB:
                continue
            storage = max(a, b)
            break

    if storage is None:                      # lone "128" form -- see _LONE_FIGURE
        for m in _LONE_FIGURE.finditer(normalized):
            val = int(m.group(1))
            if val not in _PLAUSIBLE_STORAGE_GB:
                continue
            if _OTHER_UNIT.match(normalized[m.end():]):
                continue
            storage = val
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
            if min(a, b) not in _PLAUSIBLE_RAM_GB or max(a, b) not in _PLAUSIBLE_STORAGE_GB:
                continue
            ram = min(a, b)
            break

    # Global Apple-RAM suppression, applied to EVERY path (unit-bearing,
    # bare-pair and separator alike) rather than only to the bare-pair
    # fallback. Apple does not publish RAM, so any RAM figure appearing in an
    # Apple listing came from a reseller's own wording and must never become
    # identity. Guarding only the bare-pair path let "iPhone 17 Pro 12/256GB"
    # yield ram=12 through the unit-bearing pass while "iPhone 17 Pro 256 ГБ"
    # yielded None, splitting one phone into two canonical products
    # (apple-17-pro-12-256-silver and apple-17-pro-256-silver) -- a split
    # offer pool and two different displayed prices.
    stated_ram = ram
    if brand in BRANDS_WITHOUT_PUBLISHED_RAM:
        ram = None

    return ram, storage, stated_ram


def extract_memory(
    raw: str | None, normalized: str, brand: str | None
) -> tuple[int | None, int | None]:
    """Return (ram_gb, storage_gb). Either may be None."""
    ram, storage, _ = scan_memory(raw, normalized, brand)
    return ram, storage
