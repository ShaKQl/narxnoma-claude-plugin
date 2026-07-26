# market.beeline.uz (BeeMarket) — REST GET, single card

Reference implementation: [`fill_beemarket_prices.py`](../../fill_beemarket_prices.py)

Beeline's own retail storefront. Single canonical card per variant — no reseller
spread — so the best exact match's price is the answer directly.

---

## 1. Endpoint

```
GET https://market.beeline.uz/api/web/search?q=<text>&is_bshop=1&page=<1-based>
```

No auth.

```http
Accept: */*
Accept-Language: ru
Referer: https://market.beeline.uz/
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36
```

- `is_bshop=1` restricts to the BeeMarket shop catalogue — keep it
- `page` is **1-based**
- Read `data.last_page` and stop; 3 pages is ample

## 2. Response shape

Note the **doubly-nested `data`** — a common source of `KeyError`:

```jsonc
{
  "code": 200,
  "data": {
    "data": [
      {
        "name": "Honor X9d, Midnight Black, 12/256 GB",
        "slug": "honor-x9d-point-midnight-black-point-12256-gb",
        "category": {"slug": "smartfony"},
        "actual_price": 5290000,     // current price, PLAIN SUM
        "price": 5990000             // pre-discount list price
      }
    ],
    "last_page": 3
  }
}
```

| Field | Meaning |
|---|---|
| `actual_price` | **use this** — current displayed price, plain SUM, discount applied |
| `price` | struck-through pre-discount price — do not use |
| `name` | carries RAM + storage + colour, comma-separated |
| `slug` | URL slug |
| `category.slug` | needed for the URL; default `smartfony` if absent |

Fallback chain used in practice: `actual_price` → `discount_price` → `price`.

## 3. Product URL

```
https://market.beeline.uz/<category.slug>/<slug>
```

e.g. `https://market.beeline.uz/smartfony/honor-x9d-point-midnight-black-point-12256-gb`

Note BeeMarket encodes a literal `.` in names as the token `point` inside the slug —
another reason to use the API's `slug` verbatim rather than generating one.

## 4. Query building — broad, because the search is strict AND

BeeMarket's search ANDs every term, so an over-specific query returns **zero**
results. Collapse `12/256` to just the storage and drop colour/marketing tokens:

```python
_DROP_FROM_QUERY = set(COLOR_MAP.keys()) | {
    "awesome", "5g", "4g", "xiaomi", "point", "sim", "esim", "nanosim",
    "nano", "gb", "гб", "tb", "тб",
}

def build_query(name_ru):
    n = re.sub(r"^\s*Смартфон\s+", "", name_ru).strip()
    n = re.sub(r"\b(\d{1,2})[/ ](\d{2,4})\b", r"\2", n)   # "12/256" → "256"
    toks = [t for t in n.split() if t.lower() not in _DROP_FROM_QUERY]
    return re.sub(r"\s+", " ", " ".join(toks)).strip()
```

Precision is restored entirely by the matcher. `xiaomi` is dropped because BeeMarket
lists those phones as plain `Redmi …`.

## 5. Gotchas

- **The `SIM+eSIM` phantom token.** BeeMarket names contain `SIM+eSIM`. Blindly
  mapping `+` → `plus` created a spurious `plus` model token that rejected **every
  iPhone**. Only trailing `+` is a real modifier:
  ```python
  t = re.sub(r"\+(?=\s|$)", " plus ", t)   # "Pro+" → "pro plus"
  t = t.replace("+", " ")                  # "SIM+eSIM" → "sim esim"
  ```
- Names put colour in the middle (`"Honor X9d, Midnight Black, 12/256 GB"`), so
  parse by tokens, not position.
- Accessories carry no storage — the matcher's "target has storage, candidate has
  none → reject" rule removes them for free.

## 6. Result

**57/66 (86 %)**.
