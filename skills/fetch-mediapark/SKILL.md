---
name: fetch-mediapark
description: Use when fetching prices from mediapark.uz, when asked to sweep mediapark's catalogue, or when a mediapark product slug disagrees with its name.
---

# mediapark.uz — autocomplete only, no sweep

Notes: `docs/parsers/mediapark.md`. Client: `narxnoma-crawler/narxnoma/sources/mediapark.py`.

## Run

```bash
cd narxnoma-crawler   # pip install -e . once
python -m narxnoma.cli fetch --source mediapark --query "Samsung Galaxy A17 6/128 Black"
python -m narxnoma.cli fetch --source mediapark --query "iPhone 16 128"     # Apple: capacity, no GB
```

`fetch --source mediapark` without `--query` exits 1: `can_sweep = False`.
There is no catalogue endpoint and no pagination; a sweep is structurally
impossible. Reach it per known variant (`pipeline/backfill.py` does this after
clustering).

## Endpoint

```
GET https://api.v2.mediapark.uz/v1/diginetica/autocomplete?st=<text>&lang=ru
Accept-Language: ru
Origin: https://mediapark.uz
Referer: https://mediapark.uz/
x-device-id: <any value>      # must be present, any string
x-session-id: <any value>
```

Parameter is `st`, not `q`. Returns top ~5–10 ranked hits in one call.

## Price and URL

- `products[].price` (string) — run through `coerce_price`. `oldPrice` unused.
- `linkUrl` verbatim, prefixed with `https://mediapark.uz`. Route resolves by
  the trailing numeric id; **the slug lies** (`...8-128-gb...` on a 256 GB
  phone). Never parse or rebuild it.

## Query — opposite of strict-AND sites

Ranking engine, not a filter: keep the query near-verbatim, including the
`6/128` form and colour, so the exact variant ranks into the short list.
Strip only the `Смартфон` prefix and `GB`. Aggressive stripping measurably
worsens recall here.

## Traps

- `SAMSUNG SM-A075F A07`: skip mixed alphanumeric tokens ≥ 5 chars; never
  require the word `galaxy`.
- No per-item category; the `categories` key is suggestion links, unrelated to items.
- Headless browsers hit bot detection; JSON is the only route.

Fixture: `tests/fixtures/sources/mediapark.json`. Tests: `tests/sources/test_mediapark.py`.
