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

    # Both pair regexes are zero-width: the two figures are captured inside a
    # lookahead instead of being consumed, so re.finditer's matches can overlap.
    # A model number directly adjacent to RAM ("Redmi Note 15 12/256" normalises
    # to "redmi note 15 12 256") would otherwise make the model+RAM pair
    # ("15", "12") consume "12" and hide the real memory pair ("12", "256") from
    # ever being scanned. See "The phantom-RAM trap" below.
    if storage is None:                       # bare "6 128" form
        for m in re.finditer(r"(?<![a-zа-я\d])(?=(\d{1,3})\s+(\d{2,4})(?!\d))", n):
            a, b = int(m.group(1)), int(m.group(2))
            if max(a, b) not in PLAUSIBLE_STORAGE_GB:
                continue
            storage = max(a, b); break

    # LONE figure: a capacity with neither a unit nor a partner. Every rule
    # above needs one or the other, so "Apple iPhone 12 pro 128 Синий" read as
    # no memory at all and the listing was unkeyable — while
    # "Apple iPhone 12 128 Алый" read 128 correctly, purely because the model
    # number happened to sit beside the capacity. Common rather than exotic:
    # uzum states memory in a per-SKU characteristic whose value is often the
    # bare figure (Память: "128"), which reaches the name with nothing beside
    # it. A lone figure is weaker evidence than a pair, so it is admitted only
    # from PLAUSIBLE_STORAGE_GB and only when NOT followed by a unit marking it
    # as something else — 64 (МП), 128 (mp) and 512 all appear in blurbs.
    if storage is None:                       # lone "128" form
        for m in re.finditer(r"(?<![a-zа-я\d])(\d{2,4})(?!\d)", n):
            val = int(m.group(1))
            if val not in PLAUSIBLE_STORAGE_GB:
                continue
            if re.match(r"^\s*(mp|мп|mah|мач|hz|гц|mm|мм|w|вт|nm|нм|dpi|ppi|fps)\b",
                        n[m.end():]):
                continue
            storage = val; break

    # A bare "12 256" pair normally means RAM/storage. "iPhone 16 256 GB" has the
    # identical shape — see "The phantom-RAM trap" below — so require a real
    # separator in the RAW string, and never infer RAM for Apple.
    has_pair_sep = bool(re.search(r"\d\s*[/\\+|]\s*\d", str(name or "")))
    if ram is None and (has_pair_sep or brand != "apple"):
        for m in re.finditer(r"(?<![a-zа-я\d])(?=(\d{1,2})\s+(\d{2,4})(?!\d))", n):
            a, b = int(m.group(1)), int(m.group(2))
            if min(a, b) not in PLAUSIBLE_RAM_GB or max(a, b) not in PLAUSIBLE_STORAGE_GB:
                continue
            ram = min(a, b); break

    # GLOBAL Apple-RAM suppression — see "Apple RAM suppression is global" below.
    # This runs after EVERY path, not just the bare-pair fallback above.
    stated_ram = ram                      # what the retailer actually wrote
    if brand == "apple":
        ram = None

    tokens = set(n.split())
    colors = {COLOR_MAP[t] for t in tokens if t in COLOR_MAP}

    # stated_ram is reserved as well as ram: a SUPPRESSED memory figure is
    # still a memory figure and must not fall through into model_tokens.
    reserved_nums = {str(storage or ""), str(ram or ""), str(stated_ram or ""),
                     "5g", "4g", "0"}
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
            if t.isdigit() and int(t) in {(storage or -1), (ram or -1),
                                          (stated_ram or -1)}:
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

Plausibility alone isn't enough, though — `continue` only helps if there is a next
candidate *to* continue to. A two-digit model number sitting directly in front of a
two-digit RAM value (`"Redmi Note 15 12/256"` normalises to `"redmi note 15 12 256"`)
has the same non-overlapping problem the lookbehind was built to avoid: a plain
consuming regex finds `"15 12"` first, rejects it on plausibility, and then has already
consumed the `"12"` — so the real pair `"12 256"` is never offered as a candidate at
all, and `ram` comes back `None` even though scanning "past" the rejected pair looks
like it should have worked. That's why both pair regexes are zero-width (the two
figures live inside a lookahead, matched but not consumed): `re.finditer` can then
return overlapping candidates, so after `"15 12"` is rejected, `"12 256"` is still
found starting one character later.

#### Apple RAM suppression is global, not just on the bare-pair path

`has_pair_sep or brand != "apple"` guards **only the bare-pair fallback**. The
unit-bearing pass above it has no guard at all, so an Apple listing that spells the
units out leaks RAM straight through:

```
"iPhone 17 Pro 12/256GB Silver"  → units = [12, 256] → ram = 12    ← WRONG
"iPhone 17 Pro 256 ГБ, Silver"   → units = [256]     → ram = None
```

Same phone, two canonical products — `apple-17-pro-12-256-silver` and
`apple-17-pro-256-silver` — so the offer pool splits in two and the site shows two
different prices for one product. 47 listings in the corpus are affected. Note this is
the *opposite* failure to the phantom-RAM trap above: that one **merged** distinct
models, this one **splits** a single one. Both come from the same ambiguity.

The fix is one suppression at the end of memory extraction, covering every path:

```python
if brand in BRANDS_WITHOUT_PUBLISHED_RAM:
    ram = None
```

Apple does not publish RAM. Any RAM figure in an Apple listing therefore came from a
**reseller's own wording**, not from the manufacturer, and must never become identity —
regardless of how confidently it is written (`12/256GB`, `12 GB RAM`, a separator, a
unit). The exemption for an explicit separator is gone: a separator proves the seller
*meant* a memory pair, which was never the question.

> **Suppressing RAM is not enough on its own.** `reserved_nums` is built from `ram`, so
> zeroing `ram` at the return boundary lets the figure fall through into
> `model_tokens`: `"iPhone 17 Pro 12/256GB"` keeps `"12"` as a *model* token and keys as
> `apple-12-17-pro-256-silver`. The split survives in a new place, and the reverse
> model-token check now hard-rejects the listing outright — strictly worse than the bug
> being fixed. Memory extraction must therefore return the pre-suppression figure
> (`stated_ram`) alongside, and feature extraction must reserve it.

### Why `units` collects everything

`"8ГБ/256ГБ"` normalises to `"8гб 256гб"`. A `re.search` for the *first* unit match
returns 8 → storage = 8 → every such listing rejected. On uzum this silently killed
all Honor 600 matches until fixed.

## 3. Vocabularies

```python
MODEL_MODIFIERS = {"pro", "ultra", "lite", "plus", "max", "mini", "note", "redmi",
                   "air", "fe", "se", "fold", "flip"}

NON_MODEL_TOKENS = {"gb", "гб", "tb", "тб", "smartfon", "смартфон", "iphone",
                    "apple", "samsung", "honor", "xiaomi", "vivo", "oppo",
                    "realme", "tecno", "infinix", "poco", "nothing", "google",
                    "asus", "esim", "nanosim", "sim", "nano", "point"}
```

**`"galaxy"` is deliberately absent** from `MODEL_MODIFIERS`. mediapark lists the A07
as `"SAMSUNG SM-A075F A07"` with no "Galaxy" — requiring it rejects valid matches.
Model identity comes from the `a07`/`a17`/`s26` token instead.

#### A dropped family word merges two products

The loop keeps a token only if it is digit-bearing *or* in `MODEL_MODIFIERS`. Everything
else is **silently discarded** — which is fine for `galaxy` and `z`, and catastrophic
for `fold` and `flip`:

```
"Galaxy Z Fold 7 Black 12/256"  → model_tokens = {"7"}
"Galaxy Z Flip 7 Black 12/256"  → model_tokens = {"7"}
```

Identical `model_tokens`, identical key `samsung-7-12-256-black`, `score_match` = 60,
`why()` = `"OK"`. A Fold costs roughly **double** a Flip, so the merged product shows
one median drawn from two price populations. Adding `fold` and `flip` to
`MODEL_MODIFIERS` is the whole fix.

They also join `_MODEL_PREFIX_ORDER` (with `redmi` and `note`), because they are family
words rather than trailing designators: the real name is `Galaxy Z Fold 7`, so
alphabetical ordering would render the display name as `Samsung 7 Fold`.

> The general rule this illustrates: **a word that distinguishes two products in the
> shop must be a model token.** When auditing, list every name that reduces to the same
> `model_tokens` and check none of them are actually different phones.

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
    elif c["storage"] and not t["storage"]:
        return -100                      # symmetric — see below
    if t["ram"] and c["ram"]:
        if t["ram"] == c["ram"]: score += 10
        else:                    return -100

    # Word-boundary anchored, NOT a raw substring test — see below.
    cand_tokens = set(c["n"].split())
    for mt in t["model_tokens"]:
        if mt not in cand_tokens and not re.search(rf"\b{re.escape(mt)}\b", c["n"]):
            return -100
    for mt in c["model_tokens"]:         # reverse direction — see below
        if mt not in t["n"].split() and not re.search(rf"\b{re.escape(mt)}\b", t["n"]):
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
- **Storage is symmetric; RAM is asymmetric.** This asymmetry-of-the-asymmetry is
  deliberate, and the two fields must not be treated alike:
  - Target has storage + candidate doesn't → **reject** (that's an accessory).
  - Candidate has storage + target doesn't → **reject** (see below).
  - Target has RAM + candidate doesn't → **allow**. Many retailers simply omit RAM, and
    rejecting on absence would throw away most of the market. Only a *mismatched* RAM
    rejects.
- **The reverse model-token check is essential.** It is what stops a `17 Pro Max` SKU
  from matching an `iPhone 17 Pro` target. Without it, every Pro request matches the
  more expensive Pro Max.

### A storage-less target accepts every capacity

Without the symmetric branch, a target that states no storage scores exactly

```
brand 10 + model 15 + colour 5 = 30 == ACCEPT_THRESHOLD
```

against a candidate of **any** capacity — the storage block contributes nothing and the
sum lands precisely on the threshold. Measured: `"iPhone 17 Pro Black"` accepted a
256 GB listing *and* a 1 TB listing, pooling their prices into a single median. Storage
is a hard identity field, so absence on either side must reject:

```python
elif c["storage"] and not t["storage"]:
    return -100
```

Mirror it in `why()` with a distinct message (`"target has NO storage"`) so the two
directions stay tellable apart when reading a rejection dump. RAM stays asymmetric —
absence there is genuinely "unknown", because retailers omit a RAM that exists; a
capacity, by contrast, is never omitted from a phone listing that has one.

### Model tokens must match a whole word

The fallback after the token-set test used to be a raw substring check against the
other side's normalised name. Substrings of numbers are the problem:

```
token "6"  ⊂  "iphone 16 128gb"       → iPhone 6 target accepts an iPhone 16
token "16" ⊂  "... 12 256 ..."         → any two-digit model matched a memory figure
```

Use `re.search(rf"\b{re.escape(mt)}\b", other["n"])` instead, so a token must match a
whole word. Measured against the 14,860-row golden corpus this changed **one** row: a
malformed uzum title (`"Smartfon Smartfon Samsung Galaxy S26 Ultra 6 12/256GB Oq"`)
whose stray `6` previously found a home inside the target's `256`. That row was passing
by accident, which is exactly the class of accident the boundary anchor removes.

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
    if c["storage"] and not t["storage"]:
        return "target has NO storage"
    if t["ram"] and c["ram"] and t["ram"] != c["ram"]:
        return f"ram {c['ram']}!={t['ram']}"
    ct = set(c["n"].split())
    for mt in t["model_tokens"]:
        if mt not in ct and not re.search(rf"\b{re.escape(mt)}\b", c["n"]):
            return f"target token '{mt}' missing"
    for mt in c["model_tokens"]:
        if mt not in t["n"].split() and not re.search(rf"\b{re.escape(mt)}\b", t["n"]):
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
