# idea.uz — REST GET, single card

Reference implementation: [`fill_idea_prices.py`](../../fill_idea_prices.py)

Electronics chain with broad model coverage. The simplest API of the seven — a
single GET, no auth, and it hands you the product URL so you never build one.

---

## 1. Endpoint

```
GET https://api.idea.uz/api/v2/search?search=<text>&quantity=100&type[]=shops&type[]=products
```

No auth.

```http
Accept: application/json
Accept-Language: uz
Origin: https://idea.uz
Referer: https://idea.uz/
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36
```

`type[]` is a **repeated** parameter, not a comma list. With `requests`:

```python
r = session.get(IDEA_API, params={
    "search": query,
    "quantity": 100,
    "type[]": ["shops", "products"],     # requests expands the list correctly
}, timeout=(15, 60))
```

`quantity` controls result count and is honoured up to about 100 (a live
call for "Samsung" on 2026-07-31 returned 74 products). The single-card
matcher this file originally documented only needed one match per name, so
it used `quantity=20`; the crawler's `sweep()` needs full-catalogue coverage
per brand query and uses `quantity=100` instead. There is no pagination
either way.

## 2. Response shape

```jsonc
{
  "products": [
    {
      "id": 12345,
      "name": "Honor X9d 12/256 GB Midnight Black",
      "slug": "honor-x9d-12-256-gb-midnight-black",
      "url": "https://idea.uz/ru/product/honor-x9d-12-256-gb-midnight-black",
      "current_price": 5390000        // plain SUM
    }
  ],
  "shops": [], "brands": [], "categories": []
}
```

| Field | Meaning |
|---|---|
| `current_price` | **use this** — plain SUM |
| `name` | carries RAM + storage + colour |
| `url` | **absolute product URL, ready to use** |

## 3. Product URL

Take `products[].url` **verbatim**. idea is the only source that returns a complete
absolute URL, so there is nothing to construct and nothing to get wrong.

## 4. Query building

Minimal — strip only the leading `Смартфон`:

```python
def build_query(name_ru):
    return re.sub(r"^\s*Смартфон\s+", "", name_ru).strip()
```

## 4a. Responses mix categories -- `category_id` is the only usable signal

A brand-query search (e.g. `search=Samsung`) does not return only phones. In
a 20-item recording it returned 9 smartphones alongside 7 vacuum cleaners, 3
fridges and a TV, and none of the appliances fall below the price fence, so
nothing filters them out on price alone.

The response's human-readable category fields -- `category`, `category_name`,
`category_slug` -- are `null` or `""` on every observed item, on both phones
and appliances alike. The only field that actually distinguishes them is the
undocumented `category_id`. Observed mappings (from the recorded fixture and
a live "Samsung" sweep, both 2026-07-31):

| `category_id` | Category |
|---|---|
| `55` | Smartphones (e.g. Galaxy S25 Ultra, Galaxy A36) |
| `26` | Vacuum cleaners |
| `24` | Fridges |
| `9` | TVs |

**These ids are undocumented by idea** -- there is no field, header, or docs
page that names them; they were derived purely by observing which products
carried which id. The crawler (`narxnoma/sources/idea.py`) filters `sweep()`
output to `PHONE_CATEGORY_IDS = frozenset({55})` and logs the full category
distribution seen on every sweep, specifically so that a renumbering or a
second phone category being added shows up in the logs instead of silently
emptying or polluting the catalogue.

## 5. Gotchas

- **SKU codes read as model tokens.** idea appends manufacturer part numbers to
  names, e.g. `SM-A376EZADSOZ`. Parsed as a model token, it rejects an otherwise
  perfect match. Skip alphanumeric tokens of length ≥ 5 that mix letters and digits —
  genuine model designators (`a07`, `a17`, `x9d`) are ≤ 4 characters. This was the
  first site where the rule became necessary; it was later back-ported to all others.
- **Clear the cell on a miss.** idea is where the stale-value bug surfaced: an early
  loose pass wrote ~60 values, a later strict pass matched only 54, and the ~11
  orphans silently kept prices from the wrong products. Every filler now writes
  `None` to both the price and the link cell when nothing matches:
  ```python
  if res is None:
      prices_ws.cell(row=row_idx, column=p_col).value = None
      links_ws.cell(row=row_idx, column=l_col).value = None
  ```
- `Accept-Language: uz` is what the site sends; `ru` also works but returns Russian
  names, which changes what the matcher sees. Pick one and keep it stable.

## 6. Result

**54/66 (82 %)**.
