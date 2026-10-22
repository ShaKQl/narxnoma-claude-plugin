# openshop.uz — REST POST, full-catalogue sweep

Client: [`narxnoma/sources/openshop.py`](../../narxnoma-crawler/narxnoma/sources/openshop.py)
Fixture: `tests/fixtures/sources/openshop.json` · Tests: `tests/sources/test_openshop.py`

Single-seller shop (OpenShop, stores in Tashkent). Next.js front end over a Laravel
JSON API. **The whole catalogue — 5,723 products on 2026-10-14 — comes down in ~120
requests (~2.5 min)**, so it is swept and matched locally, never searched per product.

Verified live 2026-10-14 and 2026-10-22: full sweep, 191 matched links each re-read
from the product API and the public page, six opened in a browser; `cli fetch` for
all seven categories; live contract test.

---

## 1. Transport

```
Base: https://web.openshop.uz/api/v1
Every call is POST. Filters go in the QUERY STRING, not the body.
```

```http
Accept: application/json, text/plain, */*
Accept-Language: ru
language: ru            # custom header; without it names come back in Uzbek
Origin: https://openshop.uz
Referer: https://openshop.uz/
```

No auth, no token, no cookies needed. The API advertises `x-ratelimit-limit: 120`
(per minute); the client enforces ≥ 0.55 s between requests on its own
(`MIN_INTERVAL`), independent of `NARXNOMA_MIN_DELAY`.

## 2. Endpoints

| Endpoint | What it is | Use |
|---|---|---|
| `POST /shop/product/get_products?category_id=&page=&per_page=48&sort_by=latest` | the catalogue browse the category pages call | **the sweep** |
| `POST /shop/category/categories_tree`, body `{}` | 3-level category tree with `products_count` | sweep plan, product type |
| `POST /shop/product/get_product?slug=<slug>`, body `{"with_variants": true}` | one product + its variant group | verification |
| `POST /shop/product/search_product?q=<text>` | header search box | humans only — §4 |

`get_products` also accepts `subcategory_id`, `subsubcategory_id`, `brand_id`,
`search`, `price_min`, `price_max`, and `*_slug` forms. They were read out of the
front-end bundle (`buildShopFilterQueryParams` → `/shop/product/get_products?…`),
which is only loaded on a category page — the homepage bundles do not contain it.

Response:

```json
{"data": [ {"id": 133328, "name": "Смартфон Samsung Galaxy A27 5G 8/256GB Синий",
            "slug": "133328-samsung-galaxy-a27-5g-8-256gb-moviy-smartfoni",
            "brand_name": "Samsung", "category_id": 11, "subcategory_id": 4,
            "subsubcategory_id": 20, "is_stock": true,
            "price": {"total": 4268000, "old_price": 4268000, "discount": 0, "currency": "UZS"},
            "link": "https://web.openshop.uz/shop/product/133328-…", "group": {"id": 98, "variants_count": 6},
            "tags": "…", "installment": {…}, … } ],
 "meta": {"current_page": 1, "last_page": 36, "per_page": 12, "total": 432}}
```

> **`/shop/category/<slug>` in the bundle is a front-end ROUTE, not an API path.**
> POSTing it to the API host returns HTTP 200 with an empty `data` — a "success"
> that is really a miss.

## 3. TRAPS in the sweep

1. **`per_page` is capped at 48.** Asking for 100 or 500 silently returns 48 and
   `meta.per_page` says 48. Smaller values are honoured.
2. **Deep paging stops at ~2,400 results per query.** An unfiltered walk reported
   `meta.total = 5731` but repeated earlier products from page 51 on. Walk each of
   the 11 **top-level categories** separately (largest ~1,577) and every product
   comes back. `iter_catalogue()` does this; `iter_raw()` logs a warning whenever a
   query's `total` exceeds the cap.
3. **Only in-stock goods are browsable** (`is_stock: true` on all 5,723). "Not found"
   can mean "sold out".
4. Sweep categories map to `subcategory_id` plus a third-level filter
   (`CATEGORY_SUBSUBCATEGORY_IDS`): TVs 30, ACs 31, fridges 33+34, washers 44+1411,
   ovens 32+1215+1403. **Countertop mini-ovens** sit in 1215 ("Духовые шкафы") and
   are dropped by title — no other source files them under `ovens`.

## 4. Why not the search endpoint

`search_product?q=` is fuzzy over the SEO `tags` field and capped at **60**
results: `q=Honor X9d` returns every Honor phone, tablet, watch and earbud.
`get_products?search=` is paginated but equally fuzzy (the full name of one phone
matches ~500 products). `search()` uses the latter and returns raw listings — pick
the variant by name.

## 5. How openshop tags goods

- **Every colour × memory combination is its own product** (own `id`, `slug`,
  `price`), tied together by `group.id`.
- `get_product` → `variants.axes` lists the attribute chips (`Оперативная память`,
  `Встроенная память`, `Цвет`); `variants.matrix` lists every sibling with its own
  price and stock.
- The category tree has 3 levels; **the third level is the product type**
  (`Беспроводные наушники`, `Утюги`, `Микроволновые печи`), and for phones and
  tablets it is the brand (`1213 Honor`). Restricting candidates to the right
  third-level ids is what keeps "Galaxy Buds 2" off a *case for* the Galaxy Buds 2.
- iPhones come in three SIM variants at different prices — `(SIM + eSIM)`,
  `(eSIM + eSIM)`, `(SIM + SIM)` — plus `Apple Certified Refurbished` listings.
- `badge.supplier` and `badge.edited_at` are **internal** fields (`"public": false`)
  the API leaks: the supplier is sometimes a person's name, `edited_at` a
  days-since-edit counter. Not catalogue data — never surface, store or match on them.

## 6. Price

| Field | Meaning |
|---|---|
| `price.total` | **what the customer pays now**, after any discount — the listing price |
| `price.old_price` | struck-through price; equals `total` when not discounted |

Integer UZS. No tiyin, no pre-discount trap (unlike mediapark and radius): confirmed
in a browser on a discounted listing (2 963 000 shown, 3 282 000 struck through).

## 7. Product URL

```
https://openshop.uz/shop/product/<slug>?lang=ru
```

- The item's `link` field points at `web.openshop.uz` — the **API host**, not the shop.
- Without `?lang=ru` the page renders in Uzbek (`Narx: … so'm`).
- The page is server-rendered and its `<title>` states price and memory:
  `Смартфон Honor X9d 5G 8/256GB Midnight Black | Цвет: Чёрный | Память: 8 ГБ / 256 ГБ | Цена: 4 899 000 сум`.
  `page_title(slug)` returns it with the parsed price — an independent second copy
  of the price for verification.
- The page server answers the occasional **502**; retry before calling a link dead.

## 8. Matcher gaps its names exposed

Found by matching a 2,619-name, 118-type assortment against the openshop catalogue
and reading every pair. These are gaps in how `matching/` handles names it was not
measured on; they are **not fixed in `matching/`** (the golden corpus pins phone
behaviour) and were worked around in the caller by rewriting names before
`extract_features`:

| Name | What went wrong | Caller workaround |
|---|---|---|
| `iPhone 17 Pro 256GB … (SIM + eSIM)` | `normalize()` turns `+` followed by a space into a `plus` model token → **every iPhone rejected** | collapse to `SIM+eSIM` |
| `Redmi Note 17 Pro Max 5Г` | Cyrillic `Г` survives homoglyph folding → token `5г` | `5Г` → `5G` |
| `Galaxy Watch 4` vs `Watch 8` | non-phone path drops 1-char tokens, the model digit included → **Watch 4 matched Watch 8** | glue the digit to the word: `watch4` |
| `PRM-20MW/LA1` vs `/LA2` | `head_for_model` cuts at `/` → **LA1/LA3/LA4 all matched LA2** | split `/` into a space instead of cutting |
| `Galaxy Buds 2 Оқ` | Uzbek `қ ў ғ ҳ` escape the `[а-я]+` Cyrillic-word filter → `оқ` became identity | drop words containing any Cyrillic letter (non-phones) |
| `Honor X7e … Lite Blue` | colour "Lite Blue" read as the model word `lite` | `Lite <colour>` → `light` |
| `Galaxy Tab A11+ (WiFi)` vs `(SIM)` | same name, different good, ~22 % apart | treat tablet connectivity as identity |
| `Samsung Buds 3 Pro` | openshop drops `Galaxy` on accessories | `galaxy` is not identity off-phone |

Each is a candidate fix for `matching/`, to be measured against the golden corpus
before it lands.
