---
name: fetch-openshop
description: Use when fetching prices or listings from openshop.uz (web.openshop.uz API), when an openshop sweep stops at ~2,400 products or 48 per page, when an openshop link opens the API or an Uzbek page, or when matching a whole assortment against openshop's catalogue.
---

# openshop.uz — REST POST, full-catalogue sweep

Single-seller shop; the whole catalogue (~5,700 products) is ~120 requests.
Notes: `docs/parsers/openshop.md`. Client: `narxnoma-crawler/narxnoma/sources/openshop.py`.

## Run

```bash
cd narxnoma-crawler   # pip install -e . once
python -m narxnoma.cli fetch --source openshop --limit 50
python -m narxnoma.cli fetch --source openshop --category ovens
python -m narxnoma.cli fetch --source openshop --query "honor x9d"    # fuzzy: pick by name_raw
```

Whole catalogue, every product type, no price fence (Python):

```python
from narxnoma.sources.openshop import OpenshopSource
items = list(OpenshopSource().iter_catalogue())   # raw dicts, walked per top category
```

## Endpoint

```
POST https://web.openshop.uz/api/v1/shop/product/get_products
     ?category_id=<top id>&page=<n>&per_page=48&sort_by=latest     # filters in the QUERY STRING
Accept-Language: ru
language: ru                 # custom header; without it names are Uzbek
Origin: https://openshop.uz
Referer: https://openshop.uz/
```

- Response `{data:[items], meta:{current_page,last_page,per_page,total}}`. Stop on
  `meta.last_page`, never on an empty page.
- Also accepts `subcategory_id`, `subsubcategory_id`, `brand_id`, `search`.
- Tree: `POST /shop/category/categories_tree` body `{}` — 3 levels, the **third is
  the product type** (and the brand for phones/tablets).
- Detail: `POST /shop/product/get_product?slug=<slug>` body `{"with_variants": true}`.
- Rate limit 120/min; the client self-throttles at 0.55 s/request.

## Price

`price.total` — integer UZS, already discounted. `price.old_price` is the
struck-through figure. One field, through `coerce_price`.

## URL

`https://openshop.uz/shop/product/<slug>?lang=ru`, built from `slug`. **Never the
item's `link`** — it points at `web.openshop.uz`, the API host. Without `?lang=ru`
the page is Uzbek. The page `<title>` states the price (`… | Цена: 4 899 000 сум`);
`page_title(slug)` returns `(title, price)` for verification.

## Traps (each returns HTTP 200)

- `per_page` **capped at 48**, silently.
- **Deep paging caps at ~2,400**: an unfiltered walk said 5,731 and repeated
  products after page 50. Walk per top-level category (`iter_catalogue`).
- `/shop/category/<slug>` in the JS bundle is a front-end route; on the API host it
  returns an empty list.
- `search_product?q=` (header search) is fuzzy over SEO tags and capped at 60 —
  useless for identity.
- Every colour × memory is its own product (`group.id` ties them). iPhones come as
  `(SIM + eSIM)`, `(eSIM + eSIM)`, `(SIM + SIM)` at different prices, plus
  `Certified Refurbished`.
- Only in-stock goods are listed; "not found" can mean sold out.
- Product pages answer the odd 502 — retry before calling a link dead.
- Matching openshop names hit eight matcher gaps (`SIM + eSIM` → phantom `plus`,
  one-digit models dropped off-phone, `/` cuts appliance codes, Uzbek `қ`…): see
  `docs/parsers/openshop.md` §8 before matching outside phones.

Fixture: `tests/fixtures/sources/openshop.json`. Tests: `tests/sources/test_openshop.py`.
