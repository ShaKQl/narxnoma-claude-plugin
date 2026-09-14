---
name: fetch-texnomart
description: Use when fetching prices or listings from texnomart.uz, or when a texnomart sweep contains cases, tablets and chargers alongside phones.
---

# texnomart.uz — REST GET, single seller, broad-query sweep

Notes: `docs/parsers/texnomart.md`. Client: `narxnoma-crawler/narxnoma/sources/texnomart.py`.

## Run

```bash
cd narxnoma-crawler   # pip install -e . once
python -m narxnoma.cli fetch --source texnomart --limit 50
python -m narxnoma.cli fetch --source texnomart --category laptops
python -m narxnoma.cli fetch --source texnomart --query "iphone 16 pro"
```

## Endpoint

```
GET https://gw.texnomart.uz/api/common/v1/search/result?q=<text>&page=<1-based>&limit=20
accept-device: web
accept-region: 2
Accept-Language: uz
Origin: https://texnomart.uz
Referer: https://texnomart.uz/
```

No auth. Paginate until `data.pagination.total_page`. No catalogue browse:
`sweep()` sends one broad category word (`CATEGORY_QUERY`: `smartfon`,
`televizor`, `noutbuk`, `konditsioner`, `xolodilnik`, `stiraln`, `duxovka`)
and walks the result.

## Price

`sale_price` only. `old_price` is frequently `0` and must never be a fallback.
Integer UZS.

## URL

`https://texnomart.uz/product/detail/<id>/` from `id`. `image` is the picture.

## Category — a denylist, not an allowlist

Items carry **no category field**. On a 467-offer phone sweep, 30% were not
phones, and 15 of those formed full product keys (a tablet has brand, memory
and colour). Phones use `sources/not_a_phone.py`, a denylist of product-type
nouns: an allowlist would drop any phone whose title lacks the expected noun,
and losing a real phone is worse than admitting an accessory the matcher can
still reject. Non-phone categories keep only titles carrying the category
noun (`CATEGORY_KEEP_WORD`).

Two false positives already handled: `Черное стекло` (protector vs colour —
only the qualified protector sense counts) and `USB-адаптер` in a phone's
marketing title (charger in the box, so `adapter` is not denied).

Fixture: `tests/fixtures/sources/texnomart.json`. Tests: `tests/sources/test_texnomart*.py`, `test_not_a_phone.py`.
