---
name: fetch-olcha
description: Use when fetching prices or listings from olcha.uz, when an olcha product link 404s, or when olcha returns only 20 items per page.
---

# olcha.uz — REST GET, full-catalogue pull

Notes: `docs/parsers/olcha.md`. Client: `narxnoma-crawler/narxnoma/sources/olcha.py`.

## Run

```bash
cd narxnoma-crawler   # pip install -e . once
python -m narxnoma.cli fetch --source olcha --limit 100
python -m narxnoma.cli fetch --source olcha --category televisions
python -m narxnoma.cli fetch --source olcha --query "redmi note 14"   # sweeps smartphones, filters client-side
```

`--category` defaults to `smartphones`. `--query` has no endpoint of its own:
it sweeps the category (~23 pages, 15–30 s) and keeps names containing the
query; `--limit` counts kept rows, so it cannot drop the match.

## Endpoint

```
GET https://mobile.olcha.uz/api/v2/products?page=<n>&per_page=20&category=<alias>
Accept-Language: ru
clientmodel: web            # required
Origin: https://olcha.uz
Referer: https://olcha.uz/
```

- Host is `mobile.` — the app API. No auth.
- `per_page` capped at **20** server-side; ~460 phones is ~23 pages. Do not
  try to shortcut it.
- Category aliases in `CATEGORY_ALIASES` (`telefony`, `televizory`, `noutbuki`,
  `konditsionery`, `kholodilniki-i-morozilnye-kamery-1`, `stiralnye-mashiny`,
  `plity-gazovye-i-elektricheskie`). Leaf aliases come from `/api/v2/categories`.

Why catalogue, not search: olcha's search caps results per query; the
category pull is complete and unranked. Use this pattern on any site whose
category holds hundreds, not thousands.

## Price

`discount_price` (int) falling back to `total_price` (string) — both through
`coerce_price`. Integer UZS.

## URL

`https://olcha.uz/ru/product/view/<alias>` — `/ru/product/<alias>` without
`/view/` **404s**. Use the API's `alias` verbatim.

## Traps

- Accessories slip into the category; the storage rule drops them.
- Names can be `Samsung Galaxy A37 5G 8 128 GB Awesome Gray Green` — a match
  that looks like a colour mismatch may be right. Read the raw name before
  "fixing" a matcher.

Fixture: `tests/fixtures/sources/olcha.json`. Tests: `tests/sources/test_olcha*.py`.
