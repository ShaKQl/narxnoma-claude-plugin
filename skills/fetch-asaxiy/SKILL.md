---
name: fetch-asaxiy
description: Use when fetching prices or listings from asaxiy.uz, when looking for an asaxiy JSON API, when asaxiy titles come back in Uzbek, or when an asaxiy sweep loops re-ingesting the same products.
---

# asaxiy.uz — server-rendered HTML, no JSON API at all

The exception to "call the SPA's API": asaxiy's only `/ajax/*` routes are
login and filter plumbing. Category pages ship a complete, priced product
grid in the initial HTML. Notes: `docs/parsers/asaxiy.md`.
Client: `narxnoma-crawler/narxnoma/sources/asaxiy.py`.

## Run

```bash
cd narxnoma-crawler   # pip install -e . once
python -m narxnoma.cli fetch --source asaxiy --limit 50
python -m narxnoma.cli fetch --source asaxiy --category washers
```

No `search()`.

## Request

```
GET https://asaxiy.uz/ru/product/<category-path>            # page 1
GET https://asaxiy.uz/ru/product/<category-path>/page=<N>   # page N >= 2
Accept: text/html
Accept-Language: ru-RU,ru;q=0.9
```

- Page number is a **path segment**; `?page=2` is ignored.
- Russian by `/ru/` path. `Accept-Language` and the `_language` cookie are
  ignored; `?language=ru` only works via a 301 that `X-Requested-With:
  XMLHttpRequest` suppresses.
- Do **not** send `X-Requested-With`: the lighter fragment drops the
  `totalPages` script, the only end-of-catalogue signal.
- Category paths in `CATEGORY_PATHS`.

## Read machine attributes, not prose

Each card carries a hidden `<span id="product_cart_data_<id>" data-id
data-name data-name-ru data-price data-old-price data-img data-brand-name>`
— the values asaxiy's own cart uses. Read `data-price` (integer UZS, no
separators) and `data-name-ru`. Never parse `6 719 000 so'm`.

## URL — tied to the id, twice

Anchor: `<a href="/ru/product/<slug>" onclick="sendSelectItemEvent(<id>, this)">`.
Require that id to equal the cart block's id; drop the card otherwise. A
markup shift must cost a listing, never mint one with a neighbour's URL.

## Availability

CSS class `js-buy-guest` present = IN_STOCK, absent = OUT_OF_STOCK. Do not read
the buy href (localised: scored every Russian card out-of-stock) or the
`Нет в наличии` text (Russian-only).

## Pagination trap

An out-of-range page **301s to page 1 and serves 24 real products again**.
Stop on `let totalPages = parseInt('6', 10)` from the page's inline script
AND on the first page adding no unseen id.

## Category leaves are broader than the category

A leaf holds neighbours (e.g. freezers under fridges). Filter by the
category noun; see doc §6.

Fixtures: `tests/fixtures/sources/asaxiy_ru.html`, `asaxiy_uz.html`. Tests: `tests/sources/test_asaxiy*.py`.
