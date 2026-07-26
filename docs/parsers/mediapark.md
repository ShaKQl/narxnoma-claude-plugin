# mediapark.uz — REST GET, Diginetica autocomplete

Reference implementation: [`fill_mediapark_prices.py`](../../fill_mediapark_prices.py)

Electronics chain. The only source here where the search is an **autocomplete**
endpoint — which shapes everything about how to query it.

---

## 1. Endpoint

```
GET https://api.v2.mediapark.uz/v1/diginetica/autocomplete?st=<text>&lang=ru
```

No auth. `x-device-id` / `x-session-id` are required to be *present* but **any value
works** — they are not credentials:

```http
Accept: */*
Content-Type: application/json
Accept-Language: ru
Origin: https://mediapark.uz
Referer: https://mediapark.uz/
x-device-id: Ywh1FNq17HzyCBJ15BDZl
x-session-id: vzNu2usamNvHs6plQvNO4
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36
```

Note the query parameter is `st`, not `q` or `search`.

## 2. Response shape

```jsonc
{
  "products": [
    {
      "name": "Смартфон HONOR X9d (8/256) Midnight Black",
      "price": "5299000",                              // STRING, plain SUM
      "linkUrl": "/ru/products/view/honor-x9d-8-128-gb-32417"
    }
  ],
  "suggestions": [...],
  "categories": [...]
}
```

| Field | Meaning |
|---|---|
| `price` | plain SUM but delivered as a **string** — cast it |
| `name` | trustworthy: carries RAM, storage and colour |
| `linkUrl` | **relative** path — prefix with `https://mediapark.uz` |

## 3. TRAP — the slug lies, the id doesn't

```
name:    "Смартфон HONOR X9d (8/256) Midnight Black"     ← correct
linkUrl: "/ru/products/view/honor-x9d-8-128-gb-32417"    ← says 8/128 (!)
```

A 256 GB Silver phone can carry a slug reading `...8-128-gb...`. The route resolves
by the **trailing numeric id**, so the link still opens the right product — but the
slug must never be parsed for specs, and never reconstructed.

**Rule: match on `name`, use `linkUrl` verbatim.**

## 4. Query building — the OPPOSITE of beemarket/texnomart

This is the important asymmetry. Because it is an autocomplete ranking engine rather
than a strict AND filter, dropping the RAM half **measurably worsens** recall for
Samsung and Redmi. Keep the name nearly verbatim, including the `6/128` form and the
colour word, so the exact variant ranks into the short list:

```python
def build_query(name_ru):
    q = re.sub(r"^\s*Смартфон\s+", "", name_ru).strip()
    q = re.sub(r"\bGB\b", "", q, flags=re.I)
    return re.sub(r"\s+", " ", q).strip()
```

Do not copy the aggressive `_DROP_FROM_QUERY` approach here — it makes things worse.

## 5. No pagination

Autocomplete returns the top ~5–8 hits in a single call. There is no page parameter.
This is the main reason coverage is the lowest of the seven: if the exact variant
doesn't rank into that short list, it is simply unreachable. It is also why the query
must stay specific.

## 6. Gotchas

- **SKU codes read as model tokens.** mediapark lists the Samsung A07 as
  `"SAMSUNG SM-A075F A07"`. `A075F` parsed as a model token and rejected the match.
  Skip alphanumeric tokens of length ≥ 5 that mix letters and digits — real model
  designators (`a07`, `a17`, `x9d`, `y31d`) are ≤ 4 characters.
- **Don't require `"galaxy"`.** That same listing has no "Galaxy" in it. Model
  identity must come from the `a07`/`a17`/`s26` token, never the series word.
- Headless-browser scraping of this site fails on bot detection — the JSON API is
  the only viable route.

## 7. Result

**46/66 (70 %)** — lowest coverage, entirely due to the no-pagination short list.
