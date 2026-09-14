---
name: fetch-alifshop
description: Use when fetching prices or listings from alifshop.uz, when alifshop prices look 100x too high, or when an alifshop product link 404s.
---

# alifshop.uz — REST POST, multi-seller, price in tiyin

Notes: `docs/parsers/alifshop.md`. Client: `narxnoma-crawler/narxnoma/sources/alifshop.py`.

## Run

```bash
cd narxnoma-crawler   # pip install -e . once
python -m narxnoma.cli fetch --source alifshop --limit 60
python -m narxnoma.cli fetch --source alifshop --query "honor x9d"
```

## Endpoint

```
POST https://gw.alifshop.uz/web/client/search/full-text
Content-Type: application/json
Accept-Language: ru
service-token: service-token-alifshop     # fixed public string, not a secret
Origin: https://alifshop.uz
Referer: https://alifshop.uz/
Body: {"query": "Honor X9d", "page": 0, "size": 20}
```

- `page` is **0-based** (beemarket/texnomart are 1-based).
- `size` capped at **20** server-side; 3 pages per brand is enough for a median.
- No catalogue browse: `sweep()` loops the shared brand list
  (`sources/brand_queries.py`), one search per brand.

## Price — tiyin

`items[].price` is in **tiyin (1/100 UZS)**. Divide by 100 once, in one place
(`_coerce_tiyin_price`). A partial divisor bug yields 100x prices that still
pass plausibility fences on some rows.

## Category

Items carry no category field. `aggregations.category` is a histogram whose
bucket names (`"Смартфоны Samsung"`) the endpoint accepts back as a `category`
filter and honours server-side. Discover the bucket per brand, then re-request
filtered; fall back to unfiltered with a warning if none matches.

## URL

`https://alifshop.uz/moderated-offer/<slug>` — the obvious `/product/<slug>` **404s**.
Use the API's slug verbatim.

## Traps

- Multi-seller: `source_key` is the listing UUID, one row per partner offer.
  Never collapse sellers; price = IQR-trimmed median.
- Query is strict AND; two-shot: colour-stripped first, then verbatim.
- `+` only means `plus` when trailing a word (`Pro+`); `nanoSim+eSim` must not
  mint a `plus` model token.
- Sellers omit RAM: missing RAM on a candidate = unknown, not reject.

Fixture: `tests/fixtures/sources/alifshop.json`. Tests: `tests/sources/test_alifshop*.py`.
