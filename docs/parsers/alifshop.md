# alifshop.uz — REST POST, multi-seller

Reference implementation: [`fill_alifshop_prices.py`](../../fill_alifshop_prices.py)

Multi-seller marketplace: one variant is listed by many partners at different
prices, so the output is a **median**, not a single price. Highest raw coverage of
any source (63/66).

---

## 1. Endpoint

```
POST https://gw.alifshop.uz/web/client/search/full-text
```

No auth. The one non-obvious header is `service-token`, which is a **fixed public
string**, not a credential:

```http
Accept: application/json
Accept-Language: ru
Content-Type: application/json
service-token: service-token-alifshop
Origin: https://alifshop.uz
Referer: https://alifshop.uz/
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36
```

Body:

```json
{"query": "Honor X9d 12/256", "page": 0, "size": 20}
```

- `page` is **0-based** (unlike beemarket/texnomart, which are 1-based)
- `size` is **capped at 20** server-side — asking for more is silently ignored
- 3 pages (60 listings) is plenty for a stable median

## 2. Response shape

```jsonc
{
  "items": [
    {
      "id": "4ab27e23-1f44-4c49-8a0d-213b82ab40a1", // per-listing UUID, distinct per partner offer
      "price": 259900000,                       // TIYIN — divide by 100
      "slug": "honor-x9d-12-256-gb-midnight-black-abc123",
      "quantity": 7,
      "partner_id": 1378,
      "product": {"name": "Honor X9d 12/256 GB Midnight Black"},
      "partner": {"id": 1378, "slug": "some-seller"}
    }
  ],
  "n_pages": 4
}
```

> **Corrected 2026-07-31, live crawler client.** This section previously omitted
> `items[].id`. It is the field the crawler client (`narxnoma/sources/alifshop.py`)
> uses as `source_key` — a UUID assigned per listing by alifshop itself, distinct
> per partner offer even when `slug`, `product.name`, and `price` are identical
> across sellers. `slug` alone is not documented as guaranteed unique across
> partners and must not be relied on for dedup; `id` is. Also present but unused
> by the crawler client: `quantity` (stock count, used for availability) and
> `partner_id` (redundant with `partner.id`).

| Field | Meaning |
|---|---|
| `items[].id` | **per-listing UUID** — use this as the dedupe/upsert key, not `slug` |
| `items[].price` | **TIYIN** — divide by **100** to get SUM |
| `items[].product.name` | the string to match against |
| `items[].slug` | listing slug, used for the URL |
| `items[].quantity` | stock count; `0` means out of stock |
| `items[].partner.slug` | seller identity — useful for dedupe/diagnostics |
| `n_pages` | total pages for this query |

No per-item category or product-type field exists anywhere in this response.
`aggregations.category` is a dataset-wide histogram (10 buckets with counts) over
the *whole* result set for the query, not a per-item field — it cannot be used to
tag an individual item as phone vs. non-phone.

**But the search request accepts a `category` filter, and it genuinely narrows
server-side.** The valid values are exactly the display strings in that same
response's `aggregations.category.terms[].key` — there is no numeric id, and the
value is brand-specific ("Смартфоны Samsung", "Смартфоны Xiaomi", ...), so it has
to be read off each query's own aggregation rather than hardcoded. Measured live
on 2026-07-31:

| Request body | `n_items` | `n_pages` |
|---|---|---|
| `{"query": "Samsung", "page": 0, "size": 20}` | 1,034 | 52 |
| `{"query": "Samsung", "page": 0, "size": 20, "category": "Смартфоны Samsung"}` | 690 | 35 |
| `{"query": "Samsung", "page": 0, "size": 20, "category": "Nonexistent Category XYZ"}` | 0 | — |

The third row is what proves this is a real server-side filter and not an ignored
unknown key: a made-up category value returns nothing, and the unfiltered "Samsung"
sweep is one third non-phones — microwaves, TVs, washing machines, vacuums,
fridges, smartwatches, tablets, headphones, and phone cases — that a downstream
matcher-health table would otherwise have to absorb.

The crawler client (`narxnoma/sources/alifshop.py`) picks the phones bucket with
`phone_category_from_aggregations`: `key.casefold().startswith("смартфон")`.
**This must be a prefix test, not a substring test** — the observed bucket
"Чехлы для смартфонов" (phone cases) *contains* "смартфон" and a naive `in` check
would select it, which is exactly the non-phone noise this filter exists to
remove. "Смарт-часы" (smartwatches) starts with "смарт" but not "смартфон", so the
prefix rule correctly excludes it too. `sweep()` fetches page 0 unfiltered once per
brand to read the aggregation, re-requests page 0 with the discovered `category`,
and paginates that filtered set; if no phone-like bucket is found it logs a
warning and falls back to the unfiltered sweep for that brand.

> **Units trap:** `price` is in tiyin. `259900000 / 100 = 2,599,000 SUM`. Forgetting
> the divisor produces prices 100× too large, which is obvious — but a *partial*
> divisor bug is not, so assert the result lands in a plausible 500 K–50 M range.

## 3. Product URL — verified, and not what you'd guess

```
https://alifshop.uz/moderated-offer/<slug>
```

The intuitive `https://alifshop.uz/product/<slug>` **404s** ("Biz buni topa olmadik").
The slug returned by the API is correct; only the path prefix differs. This was
caught only by opening a generated link in a browser — do the same for any new site.

## 4. Query building — two-shot, colour-stripped first

> **Corrected 2026-07-26.** This section used to say "alifshop's search is forgiving
> enough that broad stripping isn't needed." **Measured false.** A target named with a
> marketing colour misses the listing alifshop stores under the plain Russian word:
> querying `Redmi Note 15 8/256 Glacier Blue` never returns
> `Смартфон Xiaomi Redmi Note 15 8/256 ГБ, Синий` at 2,723,000 — the cheapest genuine
> blue listing. Same for `Midnight Black` vs `Black` (2,609,000 missed).
> This is a **recall** failure, and it is exactly what the global rule
> *broad query, strict match* exists to prevent.

Run the colour-stripped query first, then the verbatim one, and dedupe by `slug`:

```python
def build_queries(name_ru):
    q = re.sub(r"^\s*Смартфон\s+", "", name_ru).strip()
    q = re.sub(r"\bGB\b", "", q, flags=re.I)
    verbatim = re.sub(r"\s+", " ", q).strip()
    broad = " ".join(t for t in verbatim.split()
                     if t.lower().strip(",()") not in set(COLOR_MAP))
    broad = re.sub(r"\s+", " ", broad).strip()
    return [broad, verbatim] if broad and broad != verbatim else [verbatim]
```

The colour is enforced in the matcher, never in the query. Keep the `12/256` form —
unlike beemarket/texnomart, alifshop does not need it collapsed.

## 5. Turning many sellers into one number

```python
listings = search_alifshop(session, build_query(name))
matched  = [l for l in listings if score_match(target, l["name"]) >= 30]
median, kept = robust_median([l["price_sum"] for l in matched])
# link = the listing whose price is closest to the median
near = min(matched, key=lambda l: abs(l["price_sum"] - median))
```

IQR stripping matters here: marketplaces carry both mis-listed accessories priced
like phones and phones priced like accessories.

## 6. Gotchas

- **`+` normalisation.** `"(nanoSim+eSim)"` appears in seller names. Converting every
  `+` to `plus` injects a phantom model token that rejects every candidate. Only
  treat `+` as `plus` when it *trails* a word (`Pro+`):
  ```python
  t = re.sub(r"\+(?=\s|$)", " plus ", t)
  t = t.replace("+", " ")
  ```
- **Colour qualifiers.** Do not map `velvet`/`light`/`golden` to colours —
  `"Velvet Grey"` → `{black, gray}` would pool Black sellers into a Grey median. The
  base colour word is always present anyway.
- Sellers frequently omit RAM. The matcher must treat a missing RAM on the candidate
  side as "unknown, don't reject", while a *mismatched* RAM is a hard reject.

## 7. Result

**63/66 (95 %)** matched — the highest count, though as a median across resellers it
is a softer number than the single-card retailers.
