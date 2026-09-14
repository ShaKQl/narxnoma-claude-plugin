---
name: fetch-idea
description: Use when fetching prices or listings from idea.uz, when an idea search answers 404, or when idea names arrive without a brand.
---

# idea.uz — REST GET, single seller, brand queries, no pagination

Notes: `docs/parsers/idea.md`. Client: `narxnoma-crawler/narxnoma/sources/idea.py`.

## Run

```bash
cd narxnoma-crawler   # pip install -e . once
python -m narxnoma.cli fetch --source idea --limit 50
python -m narxnoma.cli fetch --source idea --query "Galaxy A36"
```

## Endpoint

```
GET https://api.idea.uz/api/v2/search?search=<text>&quantity=100&type[]=shops&type[]=products
Accept-Language: uz
Origin: https://idea.uz
Referer: https://idea.uz/
```

- `type[]` is a repeated parameter (`params={"type[]": ["shops", "products"]}`).
- `quantity` honoured up to ~100. **No pagination.**
- No catalogue browse: `sweep()` runs the shared brand list and dedupes by `id`.
- **A barren query answers HTTP 404, not an empty list.** Tolerate 404 per
  query and continue; still raise on 5xx and connection errors.

## Name and price

- `name` is **brandless** (`Galaxy S25 Ultra 12/256 Titanium Blue`); use
  `title_name`, which carries the brand, falling back to `name`.
- `current_price`, integer UZS.

## Category

Responses mix appliances into every query. `category_id` is the only usable
signal (`55` = smartphones; map in `CATEGORY_IDS`); textual category fields are
null. Filter in `sweep()`, not `parse()`.

## URL

`products[].url` is a complete absolute URL. Use verbatim.

## Traps

- Part numbers in names (`SM-A376EZADSOZ`) read as model tokens: skip mixed
  alphanumeric tokens of length ≥ 5.
- `Accept-Language: uz` is what the site sends; `ru` changes names. Keep stable.

Fixture: `tests/fixtures/sources/idea.json`. Tests: `tests/sources/test_idea*.py`.
