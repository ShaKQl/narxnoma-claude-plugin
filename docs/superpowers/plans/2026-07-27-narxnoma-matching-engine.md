# Narxnoma Matching Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `narxnoma.matching` — a pure, fully-tested Python library that turns a retailer's raw product name into a canonical variant identity, and explains every rejection.

**Architecture:** Zero I/O. Every function is pure and deterministic: string in, structured features out. This is the foundation every later stage depends on — sources produce names, clustering consumes keys. It ships and is validated on its own, against 14,860 real candidate rows captured from live retailer APIs on 2026-07-26.

**Tech Stack:** Python 3.11+, pytest, ruff. No runtime dependencies — the standard library only. `requests` and `SQLAlchemy` arrive in later plans; they must never be imported from `narxnoma.matching`.

## Global Constraints

- Python 3.11 or newer (`X | None` union syntax, `frozenset` typing without imports).
- `narxnoma/matching/**` must import **nothing** outside the standard library. A test enforces this.
- All functions pure and deterministic. No network, no filesystem, no clock, no global mutable state.
- `ACCEPT_THRESHOLD = 30`. A score of exactly 30 accepts.
- Hard reject is the integer `-100`, and always wins over accumulation.
- Colour is a hard identity field. Unknown colour never equals any colour.
- Every rejection must be explainable via `why()` returning a specific string, never a generic one.
- Source of truth for behaviour: `parsers/_matching-engine.md`, `parsers/uzum.md`, `parsers/alifshop.md`. If implementation and doc disagree, verify live, then fix **both** in the same commit.
- Golden data lives at `narxnoma-seed/golden/audit_*.json` (already preserved from the audit; do not regenerate).

---

## File Structure

```
narxnoma-crawler/
  pyproject.toml                      packaging + pytest + ruff config
  narxnoma/
    __init__.py
    matching/
      __init__.py                     public API re-exports
      normalize.py                    normalize()
      colors.py                       COLOR_MAP, QUALIFIERS, colors_in_order(), primary_color()
      memory.py                       extract_memory() — RAM/storage, phantom-RAM guard
      features.py                     Features dataclass, extract_features()
      scoring.py                      score_match(), why(), ACCEPT_THRESHOLD
      keys.py                         VariantKey, variant_key(), PartialKey, resolve_partial()
      stats.py                        robust_median()
      sim.py                          is_esim_only()
  tests/
    matching/
      test_purity.py                  stdlib-only enforcement
      test_normalize.py
      test_colors.py
      test_memory.py
      test_features.py
      test_scoring.py
      test_keys.py
      test_stats.py
      test_sim.py
      test_golden.py                  14,860-row regression corpus
    fixtures/golden/                  copied from narxnoma-seed/golden/
```

Each module is small and single-purpose. `features.py` composes `normalize`, `colors` and `memory`; `scoring.py` and `keys.py` consume `Features` and nothing else.

---

### Task 1: Package scaffold and purity guard

**Files:**
- Create: `narxnoma-crawler/pyproject.toml`
- Create: `narxnoma-crawler/narxnoma/__init__.py`
- Create: `narxnoma-crawler/narxnoma/matching/__init__.py`
- Test: `narxnoma-crawler/tests/matching/test_purity.py`

**Interfaces:**
- Consumes: nothing.
- Produces: importable package `narxnoma.matching`; pytest runnable from `narxnoma-crawler/`.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "narxnoma-crawler"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.5"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] **Step 2: Create the empty packages**

`narxnoma/__init__.py`:

```python
"""Narxnoma crawler — electronics price aggregation for Uzbekistan."""
```

`narxnoma/matching/__init__.py`:

```python
"""Pure matching engine: raw retailer name -> canonical variant identity.

This package must never import anything outside the standard library.
"""
```

- [ ] **Step 3: Write the failing purity test**

`tests/matching/test_purity.py`:

```python
import ast
import pathlib

STDLIB_OK = {
    "re", "unicodedata", "dataclasses", "typing", "statistics",
    "functools", "itertools", "collections", "enum", "math",
}
MATCHING_DIR = pathlib.Path(__file__).resolve().parents[2] / "narxnoma" / "matching"


def _imported_roots(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                roots.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_matching_imports_stdlib_only():
    offenders = {}
    for path in MATCHING_DIR.glob("*.py"):
        bad = _imported_roots(path) - STDLIB_OK - {"narxnoma"}
        if bad:
            offenders[path.name] = sorted(bad)
    assert offenders == {}, f"non-stdlib imports in matching: {offenders}"
```

- [ ] **Step 4: Run the test**

Run: `cd narxnoma-crawler && pytest tests/matching/test_purity.py -v`
Expected: PASS (no modules yet, so no offenders — it becomes a real guard as modules land).

- [ ] **Step 5: Commit**

```bash
git add narxnoma-crawler/pyproject.toml narxnoma-crawler/narxnoma narxnoma-crawler/tests
git commit -m "chore: scaffold narxnoma-crawler package with matching purity guard"
```

---

### Task 2: `normalize()`

**Files:**
- Create: `narxnoma-crawler/narxnoma/matching/normalize.py`
- Test: `narxnoma-crawler/tests/matching/test_normalize.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `normalize(s: str | None) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/matching/test_normalize.py`:

```python
from narxnoma.matching.normalize import normalize


def test_lowercases_and_collapses_whitespace():
    assert normalize("  Samsung   Galaxy  A17 ") == "samsung galaxy a17"


def test_none_and_empty():
    assert normalize(None) == ""
    assert normalize("") == ""


def test_folds_yo_to_ye():
    # uzum ships both "Тёмно-зелёный" and "Темно-зеленый" for the same colour
    assert normalize("Тёмно-зелёный") == "темно зеленый"


def test_separators_become_spaces():
    assert normalize("8ГБ/256ГБ") == "8гб 256гб"
    assert normalize("Honor X9d, Midnight Black, 12/256 GB") == \
        "honor x9d midnight black 12 256 gb"


def test_trailing_plus_becomes_plus_word():
    # "Pro+" is a real model modifier
    assert normalize("Honor X5d Pro+") == "honor x5d pro plus"


def test_inner_plus_becomes_space_not_plus_word():
    # THE BUG: mapping every '+' to 'plus' injected a phantom model token
    # that rejected every iPhone on BeeMarket.
    assert normalize("SIM+eSIM") == "sim esim"
    assert "plus" not in normalize("nanoSim+eSim")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd narxnoma-crawler && pytest tests/matching/test_normalize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'narxnoma.matching.normalize'`

- [ ] **Step 3: Implement**

`narxnoma/matching/normalize.py`:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `cd narxnoma-crawler && pytest tests/matching/test_normalize.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add narxnoma-crawler/narxnoma/matching/normalize.py narxnoma-crawler/tests/matching/test_normalize.py
git commit -m "feat(matching): add normalize() with trailing-plus and yo-folding rules"
```

---

### Task 3: Colour vocabulary and primary-colour selection

**Files:**
- Create: `narxnoma-crawler/narxnoma/matching/colors.py`
- Test: `narxnoma-crawler/tests/matching/test_colors.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `COLOR_MAP: dict[str, str]`, `QUALIFIERS: frozenset[str]`, `colors_in_order(tokens: list[str]) -> list[str]`, `primary_color(tokens: list[str]) -> str | None`.

**Why `primary_color` exists:** matching compares colour *sets* (intersection), but a canonical key needs exactly one colour. `"Space Black"` maps to `{gray, black}`. In both English and Russian colour names the **base colour comes last** — `Space Black`, `Glacier Blue`, `Desert Gold`, `Тёмно-серый`. So the primary colour is the last mapped token in document order. This is why we keep token order rather than only a set.

- [ ] **Step 1: Write the failing tests**

`tests/matching/test_colors.py`:

```python
from narxnoma.matching.colors import COLOR_MAP, QUALIFIERS, colors_in_order, primary_color


def test_english_base_words():
    assert colors_in_order(["midnight", "black"]) == ["black", "black"]
    assert primary_color(["glacier", "blue"]) == "blue"


def test_primary_colour_is_the_last_mapped_token():
    # "Space Black" -> {gray, black}; the base colour is the final word.
    assert primary_color(["space", "black"]) == "black"
    assert primary_color(["desert", "gold"]) == "gold"


def test_russian_vocabulary():
    assert primary_color(["темно", "серый"]) == "gray"
    assert primary_color(["серебряный"]) == "silver"


def test_uzbek_vocabulary():
    # uzum serves uz-language card/model strings; unresolvable colours reject,
    # so every missing word here was a silent miss. See parsers/uzum.md section 8.
    assert primary_color(["kumush"]) == "silver"
    assert primary_color(["tilla"]) == "gold"
    assert primary_color(["yashil"]) == "green"
    assert primary_color(["muz"]) == "blue"
    assert primary_color(["qora"]) == "black"


def test_qualifiers_are_never_colours():
    # "Velvet Grey" -> {black, gray} would pool Black sellers into a Grey median.
    for q in ["velvet", "light", "dark", "golden", "темно", "светло", "меланж"]:
        assert q not in COLOR_MAP, f"{q} must not map to a colour"
        assert q in QUALIFIERS


def test_rang_is_not_a_colour():
    # Uzbek "Kumush rang" = "silver colour"; 'rang' is the word "colour".
    assert "rang" not in COLOR_MAP


def test_no_colour_returns_none():
    assert primary_color(["samsung", "galaxy"]) is None
    assert colors_in_order(["samsung"]) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `cd narxnoma-crawler && pytest tests/matching/test_colors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'narxnoma.matching.colors'`

- [ ] **Step 3: Implement**

`narxnoma/matching/colors.py`:

```python
"""Colour vocabulary.

Only BASE colour words are mapped. Finish/qualifier words (velvet, тёмно,
меланж) must never map: "Velvet Grey" -> {black, gray} would match a Black
listing. The base colour word is always present anyway, so qualifiers add
nothing but false positives.

An unresolvable colour must REJECT, not pass. Treating it as a wildcard let
"Конфетный" and "Хром" match both Awesome Gray and Awesome Navy at once.
"""

COLOR_MAP: dict[str, str] = {
    # --- english base words ---
    "black": "black", "midnight": "black", "obsidian": "black", "graphite": "black",
    "white": "white", "moonlight": "white", "cloud": "white",
    "silver": "silver", "meteor": "silver", "titanium": "silver",
    "gray": "gray", "grey": "gray", "space": "gray", "charcoal": "gray",
    "gold": "gold", "desert": "gold", "sunrise": "gold", "champagne": "gold",
    "sandy": "gold", "sand": "gold",
    "blue": "blue", "cyan": "blue", "ocean": "blue", "aqua": "blue",
    "navy": "blue", "sky": "blue", "glacier": "blue", "denim": "blue",
    "red": "red", "scarlet": "red",
    "brown": "brown", "reddish": "brown", "coffee": "brown",
    "green": "green", "sage": "green", "mint": "green", "emerald": "green",
    "jade": "green", "forest": "green", "marrs": "green", "agate": "green",
    "purple": "purple", "violet": "purple", "cobalt": "purple",
    "lavender": "purple", "lilac": "purple", "plum": "purple",
    "orange": "orange", "cosmic": "orange", "amber": "orange", "coral": "orange",
    "pink": "pink", "rose": "pink",
    "beige": "beige", "cream": "beige", "ivory": "beige",
    "burgundy": "burgundy", "wine": "burgundy",
    "yellow": "yellow", "lime": "yellow",
    # --- russian (uzum Цвет values; see parsers/uzum.md section 8) ---
    "черный": "black", "черное": "black", "черная": "black",
    "угольный": "gray", "серый": "gray",
    "серебряный": "silver", "серебристый": "silver", "титановый": "silver",
    "синий": "blue", "голубой": "blue", "ледяной": "blue", "бирюзовый": "blue",
    "фиолетовый": "purple", "лавандовый": "purple", "сиреневый": "purple",
    "зеленый": "green", "мятный": "green",
    "оранжевый": "orange", "манго": "orange",
    "золотой": "gold", "золотистый": "gold", "песочный": "gold",
    "бежевый": "beige", "кремовый": "beige",
    "белый": "white", "молочный": "white",
    "бордовый": "burgundy", "коричневый": "brown", "алый": "red",
    "красный": "red", "розовый": "pink", "желтый": "yellow",
    # --- uzbek (uzum card/model strings) ---
    "qora": "black", "oq": "white", "kumush": "silver", "kulrang": "gray",
    "tilla": "gold", "oltin": "gold", "sariq": "yellow", "yashil": "green",
    "kok": "blue", "moviy": "blue", "muz": "blue",
    "binafsha": "purple", "pushti": "pink", "qizil": "red",
    "jigarrang": "brown", "bej": "beige",
    # --- latin transliterations in uz-locale listings ---
    "cherniy": "black", "chernyi": "black", "beliy": "white", "seriy": "gray",
    "siniy": "blue", "goluboy": "blue", "zeleniy": "green",
    "fioletoviy": "purple", "rozoviy": "pink", "zolotoy": "gold",
    "serebristiy": "silver",
}

# Words that modify a colour but are NOT colours. Never map these.
QUALIFIERS: frozenset[str] = frozenset({
    "velvet", "light", "dark", "golden", "deep", "matte", "glossy",
    "темно", "светло", "небесно", "металлик", "меланж",
    "toq", "och",          # uzbek: dark / light
})


def colors_in_order(tokens: list[str]) -> list[str]:
    """Mapped colours, in the order their words appear."""
    return [COLOR_MAP[t] for t in tokens if t in COLOR_MAP]


def primary_color(tokens: list[str]) -> str | None:
    """The single canonical colour: the LAST mapped token.

    In both English and Russian colour names the base colour comes last
    ("Space Black", "Glacier Blue", "Тёмно-серый"), so the final mapped
    word is the identity and earlier ones are shading.
    """
    found = colors_in_order(tokens)
    return found[-1] if found else None
```

- [ ] **Step 4: Run to verify pass**

Run: `cd narxnoma-crawler && pytest tests/matching/test_colors.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add narxnoma-crawler/narxnoma/matching/colors.py narxnoma-crawler/tests/matching/test_colors.py
git commit -m "feat(matching): add ru/uz/en colour vocabulary with primary-colour rule"
```

---

### Task 4: Memory extraction and the phantom-RAM guard

**Files:**
- Create: `narxnoma-crawler/narxnoma/matching/memory.py`
- Test: `narxnoma-crawler/tests/matching/test_memory.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `extract_memory(raw: str | None, normalized: str, brand: str | None) -> tuple[int | None, int | None]` returning `(ram_gb, storage_gb)`.

**This is the highest-risk function in the library.** It caused the worst bug found so far: an iPhone 16 at 12,000,000 matching an iPhone Air target, 1.44M low. Read `parsers/_matching-engine.md` § "The phantom-RAM trap that merges Apple models" before implementing.

- [ ] **Step 1: Write the failing tests**

`tests/matching/test_memory.py`:

```python
from narxnoma.matching.memory import extract_memory
from narxnoma.matching.normalize import normalize


def mem(raw, brand=None):
    return extract_memory(raw, normalize(raw), brand)


def test_collects_all_unit_bearing_figures():
    # A re.search for the FIRST unit match returns 8 -> storage=8 -> every
    # such listing rejected. This killed all Honor 600 matches on uzum.
    assert mem("Honor 600 8ГБ/256ГБ") == (8, 256)
    assert mem("Xiaomi 12GB+512GB") == (12, 512)


def test_terabytes_convert_to_gb():
    assert mem("iPhone 17 Pro Max 1 ТБ", brand="apple") == (None, 1024)


def test_lookbehind_stops_model_being_read_as_memory():
    # Without the lookbehind, "Samsung Galaxy A17 128GB" parses the pair
    # "17 128" and yields ram=17.
    ram, storage = mem("Samsung Galaxy A17 128GB", brand="samsung")
    assert storage == 128
    assert ram != 17


def test_bare_pair_is_ram_and_storage_for_non_apple():
    assert mem("Samsung Galaxy A17 6 128", brand="samsung") == (6, 128)


def test_slash_pair_is_ram_and_storage():
    assert mem("Honor X9d 12/256 GB", brand="honor") == (12, 256)


def test_apple_bare_pair_is_NOT_ram():
    # THE BUG: "iPhone 16 256 GB" has the same shape as "12/256 GB".
    # Reading 16 as RAM moved it into reserved_nums, deleting the model
    # number from model_tokens, so iPhone 16 / 17 / Air all matched.
    # Apple never publishes RAM in consumer names.
    assert mem("Apple iPhone 16 256 GB Black", brand="apple") == (None, 256)
    assert mem("Apple iPhone 17 256 ГБ", brand="apple") == (None, 256)


def test_apple_WITH_separator_still_reads_ram():
    # olcha lists "Iphone Air Space Black 12/256 GB" -- explicit separator,
    # so it really is a memory pair even for Apple.
    assert mem("Iphone Air Space Black 12/256 GB", brand="apple") == (12, 256)


def test_single_unit_figure_classified_by_size():
    assert mem("Redmi A5 64GB") == (None, 64)
    assert mem("некий товар 8 GB") == (8, None)


def test_no_memory_at_all():
    assert mem("Чехол для iPhone 17", brand="apple") == (None, None)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd narxnoma-crawler && pytest tests/matching/test_memory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'narxnoma.matching.memory'`

- [ ] **Step 3: Implement**

`narxnoma/matching/memory.py`:

```python
"""RAM and storage extraction.

The lookbehind (?<![a-zа-я\\d]) before each figure is what stops a model
code being read as memory. See parsers/_matching-engine.md.
"""
import re

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
    if ram is None and (has_separator or brand != "apple"):
        for m in _RAM_PAIR.finditer(normalized):
            a, b = int(m.group(1)), int(m.group(2))
            if min(a, b) <= _MAX_PLAUSIBLE_RAM and max(a, b) >= 32:
                ram = min(a, b)
                break

    return ram, storage
```

- [ ] **Step 4: Run to verify pass**

Run: `cd narxnoma-crawler && pytest tests/matching/test_memory.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add narxnoma-crawler/narxnoma/matching/memory.py narxnoma-crawler/tests/matching/test_memory.py
git commit -m "feat(matching): add memory extraction with Apple phantom-RAM guard"
```

---

### Task 5: `Features` and `extract_features()`

**Files:**
- Create: `narxnoma-crawler/narxnoma/matching/features.py`
- Test: `narxnoma-crawler/tests/matching/test_features.py`

**Interfaces:**
- Consumes: `normalize()` (Task 2), `COLOR_MAP`/`QUALIFIERS`/`colors_in_order`/`primary_color` (Task 3), `extract_memory()` (Task 4).
- Produces: frozen dataclass `Features(brand, ram_gb, storage_gb, colors: frozenset[str], primary_color: str | None, model_tokens: frozenset[str], normalized: str, stated_unresolvable_color: bool)` and `extract_features(name: str | None) -> Features`.

- [ ] **Step 1: Write the failing tests**

`tests/matching/test_features.py`:

```python
from narxnoma.matching.features import Features, extract_features


def test_brand_aliases():
    assert extract_features("iPhone 17 Pro 256GB").brand == "apple"
    assert extract_features("Redmi Note 15 8/256").brand == "xiaomi"
    assert extract_features("POCO X8 Pro 8/256").brand == "xiaomi"
    assert extract_features("Honor X9d 12/256").brand == "honor"


def test_model_tokens_keep_model_numbers():
    f = extract_features("Смартфон Samsung Galaxy A17 6/128 ГБ, чёрный")
    assert "a17" in f.model_tokens
    assert f.ram_gb == 6 and f.storage_gb == 128
    assert f.primary_color == "black"


def test_air_fe_se_are_model_modifiers():
    # Without "air", an iPhone Air target carries NO model token at all,
    # and matches every other iPhone.
    assert "air" in extract_features("Apple iPhone Air 256 ГБ, Space Black").model_tokens
    assert "fe" in extract_features("Samsung Galaxy S25 FE 8/128 Navy").model_tokens


def test_pro_and_max_are_both_kept():
    f = extract_features("iPhone 17 Pro Max 256 ГБ, Silver")
    assert {"pro", "max"} <= f.model_tokens


def test_sku_codes_are_not_model_tokens():
    # idea appends part numbers ("SM-A376EZADSOZ"); mediapark lists
    # "SAMSUNG SM-A075F A07". Real designators are <= 4 chars.
    f = extract_features("SAMSUNG SM-A075F A07 4/64")
    assert "a07" in f.model_tokens
    assert not any(len(t) >= 5 and any(c.isdigit() for c in t) for t in f.model_tokens)


def test_galaxy_is_not_required():
    # mediapark lists the A07 with no "Galaxy" at all.
    assert "galaxy" not in extract_features("Samsung Galaxy A17 6/128").model_tokens


def test_memory_figures_never_become_model_tokens():
    f = extract_features("Honor X9d 12/256 GB Black")
    assert "12" not in f.model_tokens
    assert "256" not in f.model_tokens


def test_bands_are_reserved_not_model_tokens():
    f = extract_features("Samsung Galaxy A27 5G 8/256 ГБ, Черный")
    assert "5g" not in f.model_tokens


def test_unresolvable_colour_is_flagged():
    # A seller stated a colour we cannot map -> we must not treat it as
    # "no colour" (which would make it a wildcard).
    f = extract_features("Смартфон Redmi 15 8/256 Конфетный")
    assert f.primary_color is None
    assert f.stated_unresolvable_color is False  # 'конфетный' is unknown, not a QUALIFIER
    g = extract_features("Смартфон Honor X8D 8/256 Velvet Grey")
    assert g.primary_color == "gray"


def test_features_are_hashable_and_frozen():
    f = extract_features("Honor X9d 12/256 GB Black")
    assert isinstance(f, Features)
    hash(f)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd narxnoma-crawler && pytest tests/matching/test_features.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'narxnoma.matching.features'`

- [ ] **Step 3: Implement**

`narxnoma/matching/features.py`:

```python
"""Feature extraction: normalised name -> structured identity."""
import re
from dataclasses import dataclass

from narxnoma.matching.colors import COLOR_MAP, QUALIFIERS, colors_in_order, primary_color
from narxnoma.matching.memory import extract_memory
from narxnoma.matching.normalize import normalize

# "galaxy" is deliberately absent: mediapark lists the A07 as
# "SAMSUNG SM-A075F A07" with no "Galaxy". Identity comes from a07/a17/s26.
MODEL_MODIFIERS: frozenset[str] = frozenset({
    "pro", "ultra", "lite", "plus", "max", "mini", "note", "redmi",
    "air", "fe", "se",          # genuine designators, not marketing words
})

NON_MODEL_TOKENS: frozenset[str] = frozenset({
    "gb", "гб", "tb", "тб", "smartfon", "смартфон", "iphone",
    "apple", "samsung", "honor", "xiaomi", "vivo", "oppo", "realme",
    "tecno", "infinix", "poco", "nothing", "google", "asus", "huawei",
    "motorola", "zte", "meizu",
    "esim", "nanosim", "sim", "nano", "point",
    "rang", "smartfoni", "telefon", "chidamli", "zarbaga",   # uz filler
})

_BRANDS = [
    "iphone", "apple", "samsung", "honor", "xiaomi", "redmi", "vivo",
    "oppo", "realme", "tecno", "infinix", "poco", "nothing", "google",
    "asus", "huawei", "motorola", "zte", "meizu",
]
_BRAND_ALIASES = {"iphone": "apple", "redmi": "xiaomi", "poco": "xiaomi"}

_SKU_MIN_LEN = 5
_PREFIX_NOISE = re.compile(r"\b(смартфон|smartfon\w*)\b")


@dataclass(frozen=True)
class Features:
    brand: str | None
    ram_gb: int | None
    storage_gb: int | None
    colors: frozenset[str]
    primary_color: str | None
    model_tokens: frozenset[str]
    normalized: str
    stated_unresolvable_color: bool


def extract_features(name: str | None) -> Features:
    normalized = normalize(name)
    n = _PREFIX_NOISE.sub("", normalized).strip()
    n = re.sub(r"\s+", " ", n)

    brand = None
    for b in _BRANDS:
        if b in n:
            brand = _BRAND_ALIASES.get(b, b)
            break

    ram, storage = extract_memory(name, n, brand)

    tokens = n.split()
    token_set = set(tokens)
    colors = frozenset(colors_in_order(tokens))
    primary = primary_color(tokens)
    # A qualifier with no base colour means the seller described a colour we
    # could not resolve -- that must reject, never act as a wildcard.
    stated_unresolvable = bool(token_set & QUALIFIERS) and primary is None

    reserved = {str(storage or ""), str(ram or ""), "5g", "4g", "0"}
    model_tokens: set[str] = set()
    for t in token_set:
        if t in NON_MODEL_TOKENS or t in COLOR_MAP or t in QUALIFIERS or t in reserved:
            continue
        if re.fullmatch(r"\d+(?:gb|гб|tb|тб)", t):
            continue
        # Skip SKU/catalogue codes (letters+digits, len >= 5): "a075f",
        # "sm-a175f". Real designators (a07, a17, x9d, y31d) are <= 4 chars.
        if len(t) >= _SKU_MIN_LEN and any(c.isalpha() for c in t) and any(c.isdigit() for c in t):
            continue
        if any(c.isdigit() for c in t):
            if t.isdigit() and int(t) in {(storage or -1), (ram or -1)}:
                continue
            model_tokens.add(t)
        elif t in MODEL_MODIFIERS:
            model_tokens.add(t)

    return Features(
        brand=brand,
        ram_gb=ram,
        storage_gb=storage,
        colors=colors,
        primary_color=primary,
        model_tokens=frozenset(model_tokens),
        normalized=n,
        stated_unresolvable_color=stated_unresolvable,
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `cd narxnoma-crawler && pytest tests/matching/test_features.py -v`
Expected: PASS — 10 passed

- [ ] **Step 5: Commit**

```bash
git add narxnoma-crawler/narxnoma/matching/features.py narxnoma-crawler/tests/matching/test_features.py
git commit -m "feat(matching): add Features dataclass and extract_features()"
```

---

### Task 6: `score_match()` and `why()`

**Files:**
- Create: `narxnoma-crawler/narxnoma/matching/scoring.py`
- Test: `narxnoma-crawler/tests/matching/test_scoring.py`

**Interfaces:**
- Consumes: `Features` (Task 5).
- Produces: `ACCEPT_THRESHOLD: int`, `HARD_REJECT: int`, `score_match(target: Features, cand: Features) -> int`, `why(target: Features, cand: Features) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/matching/test_scoring.py`:

```python
from narxnoma.matching.features import extract_features as F
from narxnoma.matching.scoring import ACCEPT_THRESHOLD, HARD_REJECT, score_match, why


def test_exact_match_accepts():
    t = F("Смартфон Honor X9d 12/256 ГБ, черный")
    c = F("Honor X9d 12/256 GB Midnight Black")
    assert score_match(t, c) >= ACCEPT_THRESHOLD


def test_wrong_storage_hard_rejects():
    t = F("Смартфон Honor X9d 12/256 ГБ, черный")
    c = F("Honor X9d 12/512 GB Midnight Black")
    assert score_match(t, c) == HARD_REJECT
    assert "storage" in why(t, c)


def test_wrong_ram_hard_rejects():
    t = F("Смартфон Honor X9d 12/256 ГБ, черный")
    c = F("Honor X9d 8/256 GB Black")
    assert score_match(t, c) == HARD_REJECT
    assert "ram" in why(t, c)


def test_reverse_model_token_check_stops_pro_max_matching_pro():
    # Without this, every Pro request matches the more expensive Pro Max.
    t = F("Смартфон Apple iPhone 17 Pro 256 ГБ, Silver")
    c = F("Смартфон Apple iPhone 17 Pro Max 256 ГБ, Silver")
    assert score_match(t, c) == HARD_REJECT
    assert "max" in why(t, c)


def test_iphone_16_does_not_match_iphone_air():
    # The 1.44M bug: an iPhone 16 at 12,000,000 matched an iPhone Air target.
    t = F("Смартфон Apple iPhone Air 256 ГБ, Space Black")
    c = F("Apple iPhone 16 256 GB Black")
    assert score_match(t, c) == HARD_REJECT


def test_iphone_16_pro_does_not_match_iphone_17_pro():
    t = F("Смартфон Apple iPhone 17 Pro 256 ГБ, Silver")
    c = F("Apple iPhone 16 Pro 256 GB Silver")
    assert score_match(t, c) == HARD_REJECT


def test_accessory_without_storage_rejects():
    # Target has storage, candidate has none -> accessory. Free filter.
    t = F("Смартфон Honor X9d 12/256 ГБ, черный")
    c = F("Чехол для Honor X9d черный")
    assert score_match(t, c) == HARD_REJECT
    assert "NO storage" in why(t, c)


def test_missing_ram_on_candidate_is_allowed():
    # Many retailers omit RAM; a MISSING ram must not reject, only a wrong one.
    t = F("Смартфон Honor X9d 12/256 ГБ, черный")
    c = F("Honor X9d 256GB Black")
    assert score_match(t, c) >= ACCEPT_THRESHOLD


def test_colour_mismatch_rejects():
    t = F("Смартфон Honor X9d 12/256 ГБ, черный")
    c = F("Honor X9d 12/256 GB Desert Gold")
    assert score_match(t, c) == HARD_REJECT
    assert "colour" in why(t, c)


def test_candidate_with_no_resolvable_colour_rejects():
    # Dropping the colour check would make it a wildcard: "Конфетный" and
    # "Хром" matched BOTH Awesome Gray and Awesome Navy simultaneously.
    t = F("Смартфон Honor X9d 12/256 ГБ, черный")
    c = F("Honor X9d 12/256 GB Конфетный")
    assert score_match(t, c) == HARD_REJECT


def test_why_returns_ok_for_a_match():
    t = F("Смартфон Honor X9d 12/256 ГБ, черный")
    c = F("Honor X9d 12/256 GB Midnight Black")
    assert why(t, c) == "OK"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd narxnoma-crawler && pytest tests/matching/test_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'narxnoma.matching.scoring'`

- [ ] **Step 3: Implement**

`narxnoma/matching/scoring.py`:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `cd narxnoma-crawler && pytest tests/matching/test_scoring.py -v`
Expected: PASS — 11 passed

- [ ] **Step 5: Commit**

```bash
git add narxnoma-crawler/narxnoma/matching/scoring.py narxnoma-crawler/tests/matching/test_scoring.py
git commit -m "feat(matching): add score_match() and explainable why()"
```

---

### Task 7: Variant keys and partial-key resolution

**Files:**
- Create: `narxnoma-crawler/narxnoma/matching/keys.py`
- Test: `narxnoma-crawler/tests/matching/test_keys.py`

**Interfaces:**
- Consumes: `Features` (Task 5).
- Produces: frozen dataclasses `VariantKey(brand, model_tokens, ram_gb, storage_gb, color, sim_kind)` and `PartialKey(brand, model_tokens, ram_gb, storage_gb, color, sim_kind)`; functions `variant_key(f: Features, sim_kind: str) -> VariantKey | None`, `partial_key(f: Features, sim_kind: str) -> PartialKey`, `resolve_partial(partial: PartialKey, candidates: list[VariantKey]) -> VariantKey | None`, `display_name(key: VariantKey) -> str`, `slug(key: VariantKey) -> str`.

**This is the clustering contract.** `resolve_partial` returning `None` for an ambiguous partial is the behaviour that separates us from uzprice.

- [ ] **Step 1: Write the failing tests**

`tests/matching/test_keys.py`:

```python
import pytest

from narxnoma.matching.features import extract_features as F
from narxnoma.matching.keys import (
    PartialKey, VariantKey, display_name, partial_key, resolve_partial, slug, variant_key,
)


def k(name, sim_kind="dual"):
    return variant_key(F(name), sim_kind)


def test_full_key_from_complete_listing():
    key = k("Смартфон Honor X9d 12/256 ГБ, черный")
    assert key.brand == "honor"
    assert key.ram_gb == 12 and key.storage_gb == 256
    assert key.color == "black"
    assert key.sim_kind == "dual"


def test_key_is_none_when_identity_incomplete():
    # No storage at all -> cannot be a canonical variant.
    assert variant_key(F("Чехол для Honor X9d"), "dual") is None
    # No colour -> colour is a hard identity field.
    assert variant_key(F("Honor X9d 12/256 GB"), "dual") is None


def test_equal_keys_for_differently_worded_same_phone():
    a = k("Смартфон Honor X9d 12/256 ГБ, черный")
    b = k("Honor X9d 12/256 GB Midnight Black")
    assert a == b
    assert hash(a) == hash(b)


def test_case_and_punctuation_do_not_create_duplicates():
    # uzprice has "Cosmic orange" and "Cosmic Orange" as two products.
    a = k("Смартфон Apple iPhone 17 Pro Max 256 ГБ, Cosmic orange")
    b = k("Смартфон Apple iPhone 17 Pro Max 256 ГБ, Cosmic Orange")
    assert a == b


def test_esim_only_is_a_different_variant():
    dual = k("Смартфон Apple iPhone 17 Pro Max 256 ГБ, Silver", "dual")
    esim = k("Смартфон Apple iPhone 17 Pro Max 256 ГБ, Silver", "esim_only")
    assert dual != esim


def test_partial_key_resolves_when_exactly_one_candidate_matches():
    full = [k("Redmi Note 15 8/256 ГБ, черный")]
    p = partial_key(F("Redmi Note 15 256GB Black"), "dual")
    assert p.ram_gb is None
    assert resolve_partial(p, full) == full[0]


def test_partial_key_REFUSES_when_ambiguous():
    # THE RULE: both 8/256 and 12/256 exist, so a listing with no RAM is
    # genuinely ambiguous. uzprice attaches it anyway and lets it set the
    # headline price. We refuse.
    full = [
        k("Redmi Note 15 8/256 ГБ, черный"),
        k("Redmi Note 15 12/256 ГБ, черный"),
    ]
    p = partial_key(F("Redmi Note 15 256GB Black"), "dual")
    assert resolve_partial(p, full) is None


def test_partial_key_refuses_when_nothing_matches():
    full = [k("Redmi Note 15 8/256 ГБ, черный")]
    p = partial_key(F("Galaxy A17 128GB Blue"), "dual")
    assert resolve_partial(p, full) is None


def test_display_name_is_generated_not_copied():
    key = k("HONOR   x9d 12/256gb   midnight black")
    assert display_name(key) == "Смартфон Honor X9d 12/256 ГБ, Черный"


def test_slug_is_deterministic_and_url_safe():
    a = k("Смартфон Honor X9d 12/256 ГБ, черный")
    b = k("Honor X9d 12/256 GB Midnight Black")
    assert slug(a) == slug(b)
    assert slug(a) == "honor-x9d-12-256-black"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd narxnoma-crawler && pytest tests/matching/test_keys.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'narxnoma.matching.keys'`

- [ ] **Step 3: Implement**

`narxnoma/matching/keys.py`:

```python
"""Canonical variant identity.

Canonical products are permanent identities; offers are temporary
observations. A key is complete only when every identity field is known --
brand, model, RAM, storage, colour, SIM. Anything less is a PartialKey and
must be resolved unambiguously or parked.
"""
from dataclasses import dataclass

from narxnoma.matching.features import Features

SIM_KINDS = ("dual", "esim_only", "unknown")

_COLOR_RU = {
    "black": "Черный", "white": "Белый", "silver": "Серебристый",
    "gray": "Серый", "gold": "Золотой", "blue": "Синий", "red": "Красный",
    "brown": "Коричневый", "green": "Зеленый", "purple": "Фиолетовый",
    "orange": "Оранжевый", "pink": "Розовый", "beige": "Бежевый",
    "burgundy": "Бордовый", "yellow": "Желтый",
}
_BRAND_RU = {
    "apple": "Apple", "samsung": "Samsung", "honor": "Honor",
    "xiaomi": "Xiaomi", "vivo": "Vivo", "oppo": "OPPO", "realme": "Realme",
    "tecno": "Tecno", "infinix": "Infinix", "nothing": "Nothing",
    "google": "Google", "asus": "ASUS", "huawei": "Huawei",
    "motorola": "Motorola", "zte": "ZTE", "meizu": "Meizu",
}


@dataclass(frozen=True, order=True)
class VariantKey:
    brand: str
    model_tokens: frozenset[str]
    ram_gb: int
    storage_gb: int
    color: str
    sim_kind: str


@dataclass(frozen=True)
class PartialKey:
    brand: str | None
    model_tokens: frozenset[str]
    ram_gb: int | None
    storage_gb: int | None
    color: str | None
    sim_kind: str


def variant_key(f: Features, sim_kind: str) -> VariantKey | None:
    """A complete canonical identity, or None if any field is unknown."""
    if not (f.brand and f.model_tokens and f.ram_gb and f.storage_gb and f.primary_color):
        return None
    return VariantKey(
        brand=f.brand,
        model_tokens=f.model_tokens,
        ram_gb=f.ram_gb,
        storage_gb=f.storage_gb,
        color=f.primary_color,
        sim_kind=sim_kind,
    )


def partial_key(f: Features, sim_kind: str) -> PartialKey:
    return PartialKey(
        brand=f.brand,
        model_tokens=f.model_tokens,
        ram_gb=f.ram_gb,
        storage_gb=f.storage_gb,
        color=f.primary_color,
        sim_kind=sim_kind,
    )


def _compatible(partial: PartialKey, full: VariantKey) -> bool:
    if partial.brand is not None and partial.brand != full.brand:
        return False
    if partial.model_tokens != full.model_tokens:
        return False
    if partial.ram_gb is not None and partial.ram_gb != full.ram_gb:
        return False
    if partial.storage_gb is not None and partial.storage_gb != full.storage_gb:
        return False
    if partial.color is not None and partial.color != full.color:
        return False
    if partial.sim_kind != "unknown" and partial.sim_kind != full.sim_kind:
        return False
    return True


def resolve_partial(partial: PartialKey, candidates: list[VariantKey]) -> VariantKey | None:
    """Attach only when EXACTLY ONE canonical variant is compatible.

    Zero matches or two-plus matches both return None. Never guess: an
    ambiguous offer belongs in unresolved_offer, not on a product page.
    """
    matches = [c for c in candidates if _compatible(partial, c)]
    return matches[0] if len(matches) == 1 else None


def _model_label(key: VariantKey) -> str:
    return " ".join(t.upper() if any(c.isdigit() for c in t) else t.capitalize()
                    for t in sorted(key.model_tokens))


def display_name(key: VariantKey) -> str:
    """Generated from the key -- never copied from a retailer.

    Copying retailer names is exactly how a competitor ended up with
    "Cosmic orange" and "Cosmic Orange" as two separate products.
    """
    brand = _BRAND_RU.get(key.brand, key.brand.capitalize())
    color = _COLOR_RU.get(key.color, key.color.capitalize())
    return f"Смартфон {brand} {_model_label(key)} {key.ram_gb}/{key.storage_gb} ГБ, {color}"


def slug(key: VariantKey) -> str:
    parts = [key.brand, *sorted(key.model_tokens),
             str(key.ram_gb), str(key.storage_gb), key.color]
    if key.sim_kind == "esim_only":
        parts.append("esim")
    return "-".join(parts)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd narxnoma-crawler && pytest tests/matching/test_keys.py -v`
Expected: PASS — 10 passed

- [ ] **Step 5: Commit**

```bash
git add narxnoma-crawler/narxnoma/matching/keys.py narxnoma-crawler/tests/matching/test_keys.py
git commit -m "feat(matching): add variant keys with refuse-on-ambiguity resolution"
```

---

### Task 8: SIM classification and robust median

**Files:**
- Create: `narxnoma-crawler/narxnoma/matching/sim.py`
- Create: `narxnoma-crawler/narxnoma/matching/stats.py`
- Test: `narxnoma-crawler/tests/matching/test_sim.py`
- Test: `narxnoma-crawler/tests/matching/test_stats.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `is_esim_only(text: str | None) -> bool`, `sim_kind(text: str | None) -> str`; `robust_median(prices: list[int]) -> tuple[float | None, list[int]]`.

- [ ] **Step 1: Write the failing tests**

`tests/matching/test_sim.py`:

```python
from narxnoma.matching.sim import is_esim_only, sim_kind


def test_explicit_dual_markers_are_not_esim_only():
    # Checked FIRST: "SIM+eSIM" contains "esim" but is the physical variant.
    for s in ["SIM+eSIM", "nanoSim+eSim", "2 SIM", "dualSIM", "две сим"]:
        assert is_esim_only(s) is False


def test_esim_only_forms():
    # uzum encodes it three ways; all must be screened. Price gap is real:
    # 20,789,010 dual vs 18,099,000 eSIM-only for the same nominal phone.
    for s in ["17 Pro Max 256 (e-Sim)", "iPhone 17 Pro Max 256GB (eSIM)",
              "Apple iPhone 17 Air 256GB, eSIM"]:
        assert is_esim_only(s) is True


def test_no_sim_information():
    assert is_esim_only("Honor X9d 12/256 GB Black") is False


def test_sim_kind_labels():
    assert sim_kind("iPhone 17 Pro 256GB (eSIM)") == "esim_only"
    assert sim_kind("iPhone 17 Pro 256GB nanoSIM+eSIM") == "dual"
    assert sim_kind("Honor X9d 12/256 GB Black") == "unknown"
```

`tests/matching/test_stats.py`:

```python
from narxnoma.matching.stats import robust_median


def test_empty():
    assert robust_median([]) == (None, [])


def test_small_sample_is_not_stripped():
    median, kept = robust_median([100, 200, 300])
    assert median == 200
    assert kept == [100, 200, 300]


def test_iqr_strips_an_outlier():
    prices = [1000, 1010, 1020, 1030, 50000]
    median, kept = robust_median(prices)
    assert 50000 not in kept
    assert median == 1015


def test_never_returns_empty_kept():
    median, kept = robust_median([5, 5, 5, 5])
    assert kept
    assert median == 5
```

- [ ] **Step 2: Run to verify failure**

Run: `cd narxnoma-crawler && pytest tests/matching/test_sim.py tests/matching/test_stats.py -v`
Expected: FAIL — `ModuleNotFoundError` for both modules

- [ ] **Step 3: Implement**

`narxnoma/matching/sim.py`:

```python
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
```

`narxnoma/matching/stats.py`:

```python
"""Turning many seller prices into one number."""
import statistics

_MIN_SAMPLES_FOR_IQR = 4
_IQR_FENCE = 1.5


def robust_median(prices: list[int]) -> tuple[float | None, list[int]]:
    """Median after IQR outlier stripping (only strips when >= 4 samples).

    Marketplaces carry both mis-listed accessories priced like phones and
    phones priced like accessories.
    """
    ordered = sorted(prices)
    if not ordered:
        return None, []
    if len(ordered) < _MIN_SAMPLES_FOR_IQR:
        return statistics.median(ordered), ordered
    q1, _, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
    iqr = q3 - q1
    lo, hi = q1 - _IQR_FENCE * iqr, q3 + _IQR_FENCE * iqr
    kept = [p for p in ordered if lo <= p <= hi] or ordered
    return statistics.median(kept), kept
```

- [ ] **Step 4: Run to verify pass**

Run: `cd narxnoma-crawler && pytest tests/matching/test_sim.py tests/matching/test_stats.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add narxnoma-crawler/narxnoma/matching/sim.py narxnoma-crawler/narxnoma/matching/stats.py narxnoma-crawler/tests/matching/test_sim.py narxnoma-crawler/tests/matching/test_stats.py
git commit -m "feat(matching): add SIM classification and IQR-robust median"
```

---

### Task 9: Golden regression corpus

**Files:**
- Create: `narxnoma-crawler/tests/fixtures/golden/` (copied from `narxnoma-seed/golden/`)
- Create: `narxnoma-crawler/narxnoma/matching/__init__.py` (rewrite — public API)
- Test: `narxnoma-crawler/tests/matching/test_golden.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `narxnoma.matching` public API re-exports; a pinned accuracy floor.

**The corpus:** 14,860 real candidate rows captured live from all 7 retailers on 2026-07-26 across 20 targets — 357 accepted, 14,503 rejected across 157 distinct reasons. Each row has `store`, `name`, `price`, `score`, `why`. This is a free, real-world regression suite; treat a drop in agreement as a bug until proven otherwise.

- [ ] **Step 1: Copy the fixtures**

```bash
mkdir -p narxnoma-crawler/tests/fixtures/golden
cp narxnoma-seed/golden/audit_*.json narxnoma-crawler/tests/fixtures/golden/
cp narxnoma-seed/golden/targets.json narxnoma-crawler/tests/fixtures/golden/
```

- [ ] **Step 2: Rewrite the package's public API**

`narxnoma/matching/__init__.py`:

```python
"""Pure matching engine: raw retailer name -> canonical variant identity.

This package must never import anything outside the standard library.
"""
from narxnoma.matching.colors import COLOR_MAP, QUALIFIERS, primary_color
from narxnoma.matching.features import Features, extract_features
from narxnoma.matching.keys import (
    PartialKey, VariantKey, display_name, partial_key, resolve_partial, slug, variant_key,
)
from narxnoma.matching.normalize import normalize
from narxnoma.matching.scoring import ACCEPT_THRESHOLD, HARD_REJECT, score_match, why
from narxnoma.matching.sim import is_esim_only, sim_kind
from narxnoma.matching.stats import robust_median

__all__ = [
    "ACCEPT_THRESHOLD", "COLOR_MAP", "Features", "HARD_REJECT", "PartialKey",
    "QUALIFIERS", "VariantKey", "display_name", "extract_features",
    "is_esim_only", "normalize", "partial_key", "primary_color",
    "resolve_partial", "score_match", "sim_kind", "slug", "variant_key", "why",
]
```

- [ ] **Step 3: Write the failing golden test**

`tests/matching/test_golden.py`:

```python
import json
import pathlib

import pytest

from narxnoma.matching import ACCEPT_THRESHOLD, extract_features, score_match

GOLDEN = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "golden"

# Agreement floor. The corpus was generated by the same algorithm, so a
# correct implementation reproduces it almost exactly; the small allowance
# absorbs deliberate improvements (e.g. a widened colour vocabulary that
# ACCEPTS rows previously rejected).
MIN_AGREEMENT = 0.99


def _rows():
    for path in sorted(GOLDEN.glob("audit_*.json")):
        target_name = json.loads(
            (GOLDEN / "targets.json").read_text(encoding="utf-8")
        )[int(path.stem.split("_")[1]) - 1]["name"]
        for row in json.loads(path.read_text(encoding="utf-8")):
            yield target_name, row


def test_corpus_is_present_and_large():
    rows = list(_rows())
    assert len(rows) > 14000, f"expected the full corpus, got {len(rows)}"


def test_accept_reject_agreement_against_golden():
    disagreements = []
    total = 0
    for target_name, row in _rows():
        total += 1
        t = extract_features(target_name)
        c = extract_features(row["name"])
        ours_accepts = score_match(t, c) >= ACCEPT_THRESHOLD
        theirs_accepts = row["score"] >= ACCEPT_THRESHOLD
        if ours_accepts != theirs_accepts:
            disagreements.append((target_name, row["name"], row["why"], ours_accepts))

    agreement = 1 - len(disagreements) / total
    sample = "\n".join(
        f"  target={t[:44]!r} cand={c[:44]!r} golden_why={w!r} ours_accepts={o}"
        for t, c, w, o in disagreements[:15]
    )
    assert agreement >= MIN_AGREEMENT, (
        f"agreement {agreement:.4f} < {MIN_AGREEMENT} "
        f"({len(disagreements)} of {total} disagree)\n{sample}"
    )


def test_no_accepted_row_has_wrong_storage():
    """An accepted match must never disagree on storage. Invariant, not a ratio."""
    for target_name, row in _rows():
        t = extract_features(target_name)
        c = extract_features(row["name"])
        if score_match(t, c) >= ACCEPT_THRESHOLD:
            if t.storage_gb and c.storage_gb:
                assert t.storage_gb == c.storage_gb, (
                    f"accepted {row['name']!r} for {target_name!r} "
                    f"with storage {c.storage_gb} != {t.storage_gb}"
                )


def test_no_accepted_row_has_wrong_colour():
    """Colour is a hard identity field. Invariant."""
    for target_name, row in _rows():
        t = extract_features(target_name)
        c = extract_features(row["name"])
        if score_match(t, c) >= ACCEPT_THRESHOLD and t.colors:
            assert t.colors & c.colors, (
                f"accepted {row['name']!r} for {target_name!r} "
                f"with colours {sorted(c.colors)} vs {sorted(t.colors)}"
            )
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd narxnoma-crawler && pytest tests/matching/test_golden.py -v`
Expected: PASS — 4 passed. If `test_accept_reject_agreement_against_golden` fails, read the printed sample: each line names the target, the candidate and the golden rejection reason. Do not lower `MIN_AGREEMENT` to make it pass — find the behavioural difference first.

- [ ] **Step 5: Run the whole suite**

Run: `cd narxnoma-crawler && pytest -v`
Expected: PASS — all tests across all 9 modules.

- [ ] **Step 6: Commit**

```bash
git add narxnoma-crawler/tests/fixtures/golden narxnoma-crawler/tests/matching/test_golden.py narxnoma-crawler/narxnoma/matching/__init__.py
git commit -m "test(matching): pin accuracy against 14,860-row live golden corpus"
```

---

## Self-Review

**Spec coverage.** This plan implements spec §5 (canonical model, variant key, identity
rules, never-guess resolution, generated display names) and the matcher corrections in
§5's back-port list. Spec §6 schema, §4 pipeline stages, §7 web and §8–10 operations are
explicitly out of scope and belong to Plans 2–4 (see below).

**Type consistency.** `Features` field names (`ram_gb`, `storage_gb`, `colors`,
`primary_color`, `model_tokens`, `normalized`, `stated_unresolvable_color`) are used
identically in Tasks 5, 6, 7 and 9. `variant_key(f, sim_kind)` and `partial_key(f, sim_kind)`
take the same two arguments throughout. `sim_kind()` in Task 8 returns exactly the three
strings `keys.SIM_KINDS` declares.

**Known gap, deliberately deferred.** `Features.stated_unresolvable_color` is computed in
Task 5 and asserted in its tests, but `score_match` does not read it — the stricter
`target.colors and not cand.colors` check already rejects those rows. It becomes load-bearing
in Plan 3, where clustering must distinguish "colour absent" from "colour stated but
unmappable" to decide between a partial key and a rejection.

## Follow-on plans

2. **Sources + harvest** — the 7 clients behind one `Source` protocol (`sweep()` /
   `search()`), polite HTTP, Postgres schema, `raw_offer` writes. Deliverable: a real sweep
   landing in the database.
3. **Clustering + aggregation** — `extract`/`cluster`/`aggregate` stages, `unresolved_offer`,
   `variant_price` rollups, uzum spread.
4. **Web** — Next.js against the Narxnoma design.
