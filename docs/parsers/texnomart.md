# texnomart.uz — REST GET, single card

Reference implementation: [`fill_texnomart_prices.py`](../../fill_texnomart_prices.py)

Large electronics chain, single canonical card per variant.

---

## 1. Endpoint — get this one right

```
GET https://gw.texnomart.uz/api/common/v1/search/result?q=<text>&page=<1-based>&limit=20
```

> **There are two similar endpoints and only one carries prices.**
>
> | Endpoint | Use |
> |---|---|
> | `gateway.texnomart.uz/api/common/v1/search/**header**` | autocomplete only — names and ids, **no prices**. A dead end. |
> | `gw.texnomart.uz/api/common/v1/search/**result**` | **the real one** — full results with `sale_price` |
>
> Note the host also differs: `gw.` vs `gateway.`. Probing product-detail endpoints
> off the header host returns 404 for every guessed path — don't go down that road.

No auth. Headers:

```http
Accept: application/json, text/plain, */*
accept-device: web
accept-language: uz
accept-region: 2
Origin: https://texnomart.uz
Referer: https://texnomart.uz/
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36
```

`accept-region: 2` selects the price region (Tashkent). `accept-device` and
`accept-region` are both required — omitting them changes or empties the response.

## 2. Response shape

```jsonc
{
  "data": {
    "products": [
      {
        "id": 32417,
        "name": "Honor X9d 12/256GB Midnight Black",
        "sale_price": 5299000,   // current price, PLAIN SUM
        "old_price": 0           // often 0
      }
    ],
    "pagination": {"total_page": 2}
  }
}
```

| Field | Meaning |
|---|---|
| `sale_price` | **use this** — plain SUM |
| `old_price` | pre-discount, frequently `0` — never use as a fallback |
| `id` | numeric product id, used to build the URL |
| `name` | carries RAM + storage + colour |

Paginate on `data.pagination.total_page`; 3 pages is enough.

## 3. Product URL

```
https://texnomart.uz/product/detail/<id>/
```

Numeric id — no slug to get wrong. The trailing slash matters.

## 4. Query building

Same strict-AND behaviour as BeeMarket, same treatment — collapse `12/256` → `256`
and drop colour/marketing tokens (identical `_DROP_FROM_QUERY`; see
[beemarket.md](beemarket.md#4-query-building--broad-because-the-search-is-strict-and)).

## 5. Gotchas

- Accessories (cases, screen protectors) rank high for phone queries. They carry no
  storage figure, so the matcher's "target has storage, candidate has none → reject"
  rule eliminates them automatically.
- `old_price: 0` must not be used as a price fallback — always read `sale_price`.
- Same `+` → `plus` normalisation caveat as everywhere else.

## 6. Result

**50/66 (76 %)**.
