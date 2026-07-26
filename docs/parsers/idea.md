# idea.uz — REST GET, single card

Reference implementation: [`fill_idea_prices.py`](../../fill_idea_prices.py)

Electronics chain with broad model coverage. The simplest API of the seven — a
single GET, no auth, and it hands you the product URL so you never build one.

---

## 1. Endpoint

```
GET https://api.idea.uz/api/v2/search?search=<text>&quantity=20&type[]=shops&type[]=products
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
    "quantity": 20,
    "type[]": ["shops", "products"],     # requests expands the list correctly
}, timeout=(15, 60))
```

`quantity` controls result count; 20 is enough. There is no pagination.

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
