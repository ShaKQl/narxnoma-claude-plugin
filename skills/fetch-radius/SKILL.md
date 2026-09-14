---
name: fetch-radius
description: Use when fetching prices or listings from radius.uz, querying its Saleor GraphQL, when radius product links 404, or when iPhones and MacBooks are missing from a radius sweep.
---

# radius.uz — Saleor GraphQL, one row per variant

Cleanest source, smallest catalogue (~274 offers) and 4.8% of all
comparisons: judge a source by the second prices it creates. Notes:
`docs/parsers/radius.md`. Client: `narxnoma-crawler/narxnoma/sources/radius.py`.

## Run

```bash
cd narxnoma-crawler   # pip install -e . once
python -m narxnoma.cli fetch --source radius --limit 50
python -m narxnoma.cli fetch --source radius --query "galaxy a26"
```

## Endpoint

```
POST https://new.api.radius.uz/graphql/
Content-Type: application/json
Accept-Language: ru
Origin: https://radius.uz
Referer: https://radius.uz/
```

No auth. `api.radius.uz` does not resolve; `new.api.` is live. Found in the
Next.js chunks, not the network tab (site is server-rendered). GET serves a
Playground; schema is Saleor's. Queries `CATEGORY_QUERY` / `SEARCH_QUERY` in
the client; cursor pagination, `PAGE_SIZE = 100`. `Category.products` already
includes descendants.

## The variant is the offer

`Product.name` = `Samsung Galaxy A26`; `Variant.name` = `Смартфон Samsung
Galaxy A26 5G 8/256GB Black (Черный)`. Identity lives on the variant: emit
one listing per variant, `name_raw` from the variant, price from
`pricing.priceRange.start.amount` (plain UZS), `isAvailable` for stock.

Ids are base64 `Type:number` (`UHJvZHVjdFZhcmlhbnQ6ODA0Ng==` = `ProductVariant:8046`).
A malformed id costs one listing, not the sweep.

## URL — default variant id, not product id

`https://radius.uz/ru/product/<variant-id>-<product-slug>`. Product-id URLs
**404 on every product**; both ids sit beside the slug and both look right.
A non-default variant id also resolves and renders that colour.

## Category slugs — the Apple trap

`noutbuki` holds 9 laptops, none Apple; MacBooks and iPhones live under a
top-level `apple` category, absent from `smartfony`. Slugs are tuples per
category in the client so Apple is swept.

## Traps

- GraphQL failure is **HTTP 200** with `errors` and null `data`; raise on it
  and on a null `category`.
- `thumbnail(size:N).url` is non-null even when the file was never rendered:
  `.avif` sources 404. For avif only, swap `/thumbnails/<N>/` for `/media/`.

Fixtures: `tests/fixtures/sources/radius.json`, `radius_phones.json`. Tests: `tests/sources/test_radius*.py`.
