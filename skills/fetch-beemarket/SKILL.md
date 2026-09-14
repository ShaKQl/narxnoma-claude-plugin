---
name: fetch-beemarket
description: Use when fetching prices or listings from market.beeline.uz (BeeMarket), or when a BeeMarket sweep returns thousands of non-phone items.
---

# market.beeline.uz — REST GET, single seller, category endpoint

Notes: `docs/parsers/beemarket.md`. Client: `narxnoma-crawler/narxnoma/sources/beemarket.py`.

## Run

```bash
cd narxnoma-crawler   # pip install -e . once
python -m narxnoma.cli fetch --source beemarket --limit 50
python -m narxnoma.cli fetch --source beemarket --query "Honor X6c"
```

## Endpoints

Sweep — category-scoped, the request the site's own category page makes:

```
GET https://market.beeline.uz/api/web/categories/<slug>/products?page=<1-based>&is_bshop=1
```

Search — generic, honours `q`:

```
GET https://market.beeline.uz/api/web/search?q=<text>&is_bshop=1&page=<1-based>
```

Headers: `Accept-Language: ru`, `Referer: https://market.beeline.uz/`. No auth.
Both return the doubly-nested `data.data[]` list with `data.last_page`. Stop
on `last_page`.

Category slugs: `CATEGORY_SLUGS` in the client (`smartfony` = smartphones).
Adding `category=`/`category_id=` to the generic search is silently ignored —
only the separate category endpoint narrows.

## Price

`actual_price` → `discount_price` → `price` (struck-through list; last resort).
Integer UZS.

## URL

`https://market.beeline.uz/<category.slug>/<slug>` — take `slug` verbatim;
BeeMarket writes a literal `.` as `point` inside slugs.

## Traps

- Search is strict AND on product names: `q=smartfon` returns one accessory.
  Broad query, strict match.
- `SIM+eSIM` in names: only a trailing `+` is `plus`.
- Colour sits mid-name (`Honor X9d, Midnight Black, 12/256 GB`): parse by
  token, not position.
- Accessories carry no storage; the storage rule drops them.

Fixture: `tests/fixtures/sources/beemarket.json`. Tests: `tests/sources/test_beemarket*.py`.
