# The shared matching engine

Every filler uses the same name→product matcher. **This, not the search endpoint, is
what makes results correct.** Each site's search will happily return a phone case, a
different storage tier, or a different colour; the matcher is the only thing that
decides what counts.

Design rule: **broad query, strict match.** Widen recall at the HTTP layer, restore
precision here.

---

## 1. Normalisation

```python
def normalize(s):
    if not s:
        return ""
    t = str(s).lower().strip()
    for a, b in [("–", "-"), ("—", "-"), (",", " "), ("/", " "), ("|", " "), ("ё", "е")]:
        t = t.replace(a, b)
    # '+' → ' plus ' ONLY as a trailing model marker (e.g. "Pro+"). A '+' inside
    # "SIM+eSIM" is followed by a letter, so it becomes a plain space instead.
    t = re.sub(r"\+(?=\s|$)", " plus ", t)
    t = t.replace("+", " ")
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    return t
```

The `+` rule exists because of a real failure: mapping every `+` to `plus` turned
`SIM+eSIM` into a phantom `plus` model token that rejected **every iPhone** on
BeeMarket. `ё → е` matters for uzum, where `Тёмно-зелёный` and `Темно-зеленый` both
appear.

## 2. Feature extraction

```python
def extract_features(name):
    n = normalize(name)
    n = re.sub(r"\bсмартфон\b", "", n).strip()
    n = re.sub(r"\bsmartfon\b", "", n).strip()

    brand = None
    for b in ["iphone", "apple", "samsung", "honor", "xiaomi", "redmi", "vivo",
              "oppo", "realme", "tecno", "infinix", "poco", "nothing", "google", "asus"]:
        if b in n:
            brand = {"iphone": "apple", "redmi": "xiaomi"}.get(b, b)
            break

    storage = ram = None

    # Collect ALL unit-bearing figures — sellers write "8ГБ/256ГБ" and "12GB+512GB",
    # where a single-match regex reads the RAM as the storage.
    units = []
    for m in re.finditer(r"(?<![a-zа-я\d])(\d{1,4})\s*(gb|гб|tb|тб)\b", n):
        val = int(m.group(1))
        if m.group(2) in ("tb", "тб"):
            val *= 1024
        units.append(val)

    if len(units) >= 2:
        storage = max(units)
        if min(units) <= 24:
            ram = min(units)
    elif len(units) == 1:
        if units[0] >= 32: storage = units[0]
        else:              ram = units[0]

    # Plausible RAM/storage sizes for the bare-pair fallbacks below. A model
    # number ("7" in "Galaxy Z Fold 7 512 ГБ", "5" in "Galaxy Watch 5 44mm")
    # has the identical shape as a real memory pair; restricting candidates
    # to sizes retailers actually sell is what stops the model number from
    # being absorbed as RAM or storage. See "The phantom-RAM trap" below.
    PLAUSIBLE_RAM_GB = {1, 2, 3, 4, 6, 8, 10, 12, 16, 18, 24}
    PLAUSIBLE_STORAGE_GB = {32, 64, 128, 256, 512, 1024, 2048}

    if storage is None:                       # bare "6 128" form
        for m in re.finditer(r"(?<![a-zа-я\d])(\d{1,3})\s+(\d{2,4})(?!\d)", n):
            a, b = int(m.group(1)), int(m.group(2))
            if max(a, b) not in PLAUSIBLE_STORAGE_GB:
                continue
            storage = max(a, b); break

    # A bare "12 256" pair normally means RAM/storage. "iPhone 16 256 GB" has the
    # identical shape — see "The phantom-RAM trap" below — so require a real
    # separator in the RAW string, and never infer RAM for Apple.
    has_pair_sep = bool(re.search(r"\d\s*[/\\+|]\s*\d", str(name or "")))
    if ram is None and (has_pair_sep or brand != "apple"):
        for m in re.finditer(r"(?<![a-zа-я\d])(\d{1,2})\s+(\d{2,4})(?!\d)", n):
            a, b = int(m.group(1)), int(m.group(2))
            if min(a, b) not in PLAUSIBLE_RAM_GB or max(a, b) not in PLAUSIBLE_STORAGE_GB:
                continue
            ram = min(a, b); break

    tokens = set(n.split())
    colors = {COLOR_MAP[t] for t in tokens if t in COLOR_MAP}

    reserved_nums = {str(storage or ""), str(ram or ""), "5g", "4g", "0"}
    model_tokens = set()
    for t in tokens:
        if t in NON_MODEL_TOKENS or t in COLOR_MAP or t in reserved_nums:
            continue
        if re.fullmatch(r"\d+(?:gb|гб|tb|тб)", t):
            continue
        # Skip SKU/catalogue codes (letters+digits, len >= 5): "a075f", "sm-a175f".
        # Real model designators (a07, a17, x9d, y31d) are <= 4 chars.
        if len(t) >= 5 and any(c.isalpha() for c in t) and any(c.isdigit() for c in t):
            continue
        if any(c.isdigit() for c in t):
            if t.isdigit() and int(t) in {(storage or -1), (ram or -1)}:
                continue
            model_tokens.add(t)
        elif t in MODEL_MODIFIERS:
            model_tokens.add(t)

    return {"brand": brand, "ram": ram, "storage": storage,
            "colors": colors, "n": n, "model_tokens": model_tokens}
```

### The lookbehind that matters

`(?<![a-zа-я\d])` before the first number. Without it, `"Samsung Galaxy A17 128GB"`
parses as the pair `"17 128"` → **ram = 17**. The model code must not be adjacent-read
as memory.

### The phantom-RAM trap that merges Apple models

The single worst bug found so far, because it fails *silently and expensively*.

```
"Apple iPhone 16 256 GB Black"   → units = [256] → storage = 256, ram = None
                                 → bare-pair loop sees "16 256" → ram = 16   ← WRONG
```

`16` is now in `reserved_nums`, so it is **stripped from `model_tokens`**. The same
happens to `iPhone 17`. Both end up with *no model token at all*, and since the
reverse check has nothing to compare, **iPhone 16, iPhone 17 and iPhone Air all match
each other**. Measured live: an `iPhone Air 256 Space Black` target matched
`Apple iPhone 16 256 GB Black` at 12,000,000 — 1.44 M below the true Air price.

Two independent causes, both must be fixed:

1. **`normalize()` has already erased the `/`** that distinguishes `12/256` (memory)
   from `16 256` (model + memory). By the time the loop runs the shapes are
   identical — so test the **raw** string for a separator, not the normalised one.
2. **`"air"` was missing from `MODEL_MODIFIERS`**, so an `iPhone Air` target carried
   no model token even before the RAM bug. `fe` (Galaxy S25 FE) and `se` are the same
   class of genuine designator.

Apple never publishes RAM in consumer names, which is what makes
`has_pair_sep or brand != "apple"` safe: it keeps `Honor X9d 12/256` (real separator)
and `Samsung A17 6 128` (non-Apple bare form) working untouched.

> Regression test worth keeping: `iPhone 17 Pro` must reject `iPhone 17 Pro Max`,
> `iPhone 16 Pro` **and** `iPhone Air`; `Honor X9d 12/256` must still reject `8/256`.

#### The same trap recurs on Samsung — and the Apple guard doesn't cover it

`has_pair_sep or brand != "apple"` only protects brands that never publish RAM. Samsung
*does* publish RAM, so it is exempt from the guard — and it hits the identical failure
shape, because the Galaxy Z line uses a small integer as its model/generation number:

```
"Смартфон Samsung Galaxy Z Fold 7 512 ГБ Jet Black"  → bare pair "7 512" → ram = 7  ← WRONG
"Смартфон Samsung Galaxy Z Flip 7 256 ГБ Jet Black"  → bare pair "7 256" → ram = 7  ← WRONG
"Samsung Galaxy Watch 5 44mm Graphite"               → bare pair "5 44"  → ram = 5, storage = 44  ← WRONG
```

`7` then lands in `reserved_nums`, deleting the model number from `model_tokens` —
exactly the mechanism that merged `iPhone 16`/`17`/`Air`, this time merging `Z Fold 7`
and `Z Fold 6`. Checked against the project's 2,834-name corpus this misreads 13
listings, including current flagship phones.

Brand exclusion can't be the fix here (Samsung genuinely does publish RAM in most of
its listings, so blanket-excluding it would break the working cases). The general
defence is **plausibility**: constrain both bare-pair passes to values retailers
actually sell, and keep scanning past a rejected candidate instead of stopping at the
first one —

```python
PLAUSIBLE_RAM_GB = {1, 2, 3, 4, 6, 8, 10, 12, 16, 18, 24}
PLAUSIBLE_STORAGE_GB = {32, 64, 128, 256, 512, 1024, 2048}
```

The bare-pair storage loop now requires `max(a, b) in PLAUSIBLE_STORAGE_GB`; the
bare-pair RAM loop requires `min(a, b) in PLAUSIBLE_RAM_GB and max(a, b) in
PLAUSIBLE_STORAGE_GB`. Either way, on a rejected candidate the loop `continue`s to the
next regex match instead of `break`ing, which is what lets `"... 4/128 ..."` still be
found in a name whose marketing blurb also contains an unrelated `"9 120"`-shaped pair
(`6.9"` + `120Hz`). The unit-bearing pass (`8ГБ`/`256GB`) is untouched — an explicit
unit is a statement by the retailer and stays trusted as-is. The Apple guard also stays
exactly as it is; this is additional, not a replacement — Apple's case (no RAM
published at all) is still handled by `brand != "apple"`, while Samsung's case (RAM
published, but a plausible-looking model number sits right next to storage) is handled
by the plausibility sets.

### Why `units` collects everything

`"8ГБ/256ГБ"` normalises to `"8гб 256гб"`. A `re.search` for the *first* unit match
returns 8 → storage = 8 → every such listing rejected. On uzum this silently killed
all Honor 600 matches until fixed.

## 3. Vocabularies

```python
MODEL_MODIFIERS = {"pro", "ultra", "lite", "plus", "max", "mini", "note", "redmi",
                   "air", "fe", "se"}

NON_MODEL_TOKENS = {"gb", "гб", "tb", "тб", "smartfon", "смартфон", "iphone",
                    "apple", "samsung", "honor", "xiaomi", "vivo", "oppo",
                    "realme", "tecno", "infinix", "poco", "nothing", "google",
                    "asus", "esim", "nanosim", "sim", "nano", "point"}
```

**`"galaxy"` is deliberately absent** from `MODEL_MODIFIERS`. mediapark lists the A07
as `"SAMSUNG SM-A075F A07"` with no "Galaxy" — requiring it rejects valid matches.
Model identity comes from the `a07`/`a17`/`s26` token instead.

### Colour map — base words only

```python
COLOR_MAP = {
    "black": "black", "midnight": "black",
    "white": "white",
    "silver": "silver", "meteor": "silver",
    "gray": "gray", "grey": "gray", "space": "gray",
    "gold": "gold", "desert": "gold", "sunrise": "gold",
    "blue": "blue", "cyan": "blue", "ocean": "blue",
    "deep": "blue", "navy": "blue", "sky": "blue", "glacier": "blue",
    "red": "red", "brown": "brown", "reddish": "brown",
    "green": "green", "sage": "green",
    "purple": "purple", "violet": "purple", "cobalt": "purple", "lavender": "purple",
    "orange": "orange", "cosmic": "orange", "pink": "pink",
    # ... plus the Russian AND Uzbek sets — see uzum.md §8
}
```

**Never map finish/qualifier words** — `velvet`, `light`, `golden`, `тёмно`, `светло`,
`металлик`, `меланж`. `"Velvet Grey"` → `{black, gray}` would match a **Black**
listing. The base colour word is always present anyway, so qualifiers add nothing but
false positives. This was a real bug, caught and back-ported to every site.

## 4. Scoring

```python
def score_match(t, c):          # t = target features, c = candidate features
    score = 0
    if t["brand"] and c["brand"]:
        if t["brand"] != c["brand"]:
            return -100
        score += 10
    if t["storage"] and c["storage"]:
        if t["storage"] == c["storage"]: score += 20
        else:                            return -100
    elif t["storage"] and not c["storage"]:
        return -100                      # kills accessories for free
    if t["ram"] and c["ram"]:
        if t["ram"] == c["ram"]: score += 10
        else:                    return -100

    cand_tokens = set(c["n"].split())
    for mt in t["model_tokens"]:
        if mt not in cand_tokens and mt not in c["n"]:
            return -100
    for mt in c["model_tokens"]:         # reverse direction — see below
        if mt not in t["n"].split() and mt not in t["n"]:
            return -100
    if t["model_tokens"] or c["model_tokens"]:
        score += 15

    if t["colors"] and c["colors"]:
        if not (t["colors"] & c["colors"]):
            return -100
        score += 5
    return score

ACCEPT_THRESHOLD = 30
```

Key properties:

- **Hard reject (`-100`) beats accumulation.** A wrong storage can never be
  out-scored by matching brand + colour.
- **Asymmetric on missing data.** Target has storage + candidate doesn't → reject
  (that's an accessory). Target has RAM + candidate doesn't → allowed (many retailers
  omit RAM).
- **The reverse model-token check is essential.** It is what stops a `17 Pro Max` SKU
  from matching an `iPhone 17 Pro` target. Without it, every Pro request matches the
  more expensive Pro Max.

> Only apply the reverse check to a **curated** candidate string. On uzum the raw card
> title is a marketing blurb (`6.7" AMOLED 90Гц, камера 50Мп, 5000 мАч`) whose stray
> numbers become model tokens and reject everything. See
> [uzum.md §5](uzum.md#5-trap-1--card-price--product-price).

## 5. Unresolvable colours must reject, not pass

If a candidate states a colour you cannot map, dropping the colour check makes it a
**wildcard**. On uzum, `Конфетный` (candy) and `Хром` matched *both* the Awesome Gray
and Awesome Navy targets at once.

```python
if target["colors"] and cand["color_raw"] and not cand["color_known"]:
    continue        # seller stated a colour we can't resolve → can't confirm
```

Pair this with a comprehensive colour map so rejection stays rare and genuinely means
"unresolvable".

## 6. Debugging a rejection

Score alone doesn't tell you *why*. This mirror of `score_match` is worth keeping:

```python
def why(t, c):
    if t["brand"] and c["brand"] and t["brand"] != c["brand"]:
        return f"brand {c['brand']}!={t['brand']}"
    if t["storage"] and c["storage"] and t["storage"] != c["storage"]:
        return f"storage {c['storage']}!={t['storage']}"
    if t["storage"] and not c["storage"]:
        return "cand has NO storage"
    if t["ram"] and c["ram"] and t["ram"] != c["ram"]:
        return f"ram {c['ram']}!={t['ram']}"
    ct = set(c["n"].split())
    for mt in t["model_tokens"]:
        if mt not in ct and mt not in c["n"]:
            return f"target token '{mt}' missing"
    for mt in c["model_tokens"]:
        if mt not in t["n"].split() and mt not in t["n"]:
            return f"cand token '{mt}' extra"
    if t["colors"] and c["colors"] and not (t["colors"] & c["colors"]):
        return f"colour {c['colors']} vs {t['colors']}"
    return "OK"
```

Every matcher fix in this project came from dumping candidates with `why()` and
reading them, not from guessing.

## 7. Validating a run

Two checks catch most regressions:

1. **min far below median → suspect.** Flag rows where `min / median < 0.88` and read
   the matched names. This is exactly how the uzum card-vs-SKU memory bug was found —
   the min was a 6/128 masquerading as an 8/256.
2. **Link ⟺ price consistency.** Every filled price must have a link and vice versa,
   per column. A mismatch means a partial write or a stale value.

Then open at least one generated link per site in a real browser and confirm the
rendered price and variant match the cell.
