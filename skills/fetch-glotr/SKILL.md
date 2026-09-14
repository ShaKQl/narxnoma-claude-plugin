---
name: fetch-glotr
description: Use when asked to fetch listings from glotr.uz (robots.txt forbids it; only with the site's written permission), when every glotr picture belongs to the neighbouring product, or when a glotr sweep ingests far more rows than the category holds.
---

# glotr.uz — server-rendered classifieds board

**Access first.** glotr's `robots.txt` disallows the browse surface
(`/search`, `/*?catid=`, `/*?page=`, `Crawl-delay: 10`) for every user agent
and names `ClaudeBot`/`GPTBot`/`CCBot` with `Disallow: /`. The original
operator swept it under an **explicit written grant from glotr**. That grant
does not travel with this code. Do not run this client against glotr.uz
without your own permission from them, and do not copy the approach to
another site whose robots.txt says the same.

Notes: `docs/parsers/glotr.md`. Client: `narxnoma-crawler/narxnoma/sources/glotr.py`.

## Run (with permission)

```bash
cd narxnoma-crawler   # pip install -e . once
python -m narxnoma.cli fetch --source glotr --category ovens --limit 50
```

No `search()`.

## Request

```
GET https://glotr.uz/<category-path>/            # page 1
GET https://glotr.uz/<category-path>/?page=N
Accept-Language: ru-RU,ru;q=0.9
```

No auth. Yii-rendered, UTF-8. 56 cards per page. `--category` maps to the
path via `CATEGORY_PATHS`:

| `--category` | path |
|---|---|
| smartphones | `telefoni-i-plansheti` |
| televisions | `televizori` |
| laptops | `noutbuki` |
| acs | `konditsioneri` |
| fridges | `xolodilniki` |
| washers | `stiralnie-mashini` |
| ovens | `duxovie-shkafi` |

robots.txt states `Crawl-delay: 10`. Honour it even under a grant:
`NARXNOMA_MIN_DELAY=10 NARXNOMA_MAX_DELAY=12`.

## A classifieds board, not a shop

Sellers post into any category they like. Every category page is noisy:
filter with **positive keeps** (title must carry the category noun) plus an
accessory drop — never a denylist alone. See doc §6.

## Card — the photos come before the name

```
<div class='product-card '>
  header:  <a href="/<slug>-p-<id>/"> <img data-src=... alt=...>   (photos)
  content: <a href='/<slug>-p-<id>/' class='product-card__link'>name</a>
           <span class='text-stock text-success'>В наличии</span>
           <div class="price-retail proposal-price"> 2 610 800 <span>сум</span></div>
```

Cut cards at `<div class='product-card '` (encloses both halves). Read the
`-p-<id>` **twice** — photo anchor and name anchor — and drop the card when
they disagree. Cutting at the name anchor gave 55/55 listings their
neighbour's picture while every count stayed green.

## Price and availability

Price text `7 579 000` — strip spaces, `coerce_price`. Cards with no price
("цена по запросу") are dropped with a warning.
`text-success` = IN_STOCK; `text-warning` (под заказ), `text-secondary`
(уточнить), absent = UNKNOWN. **Nothing maps to OUT_OF_STOCK**: sellers
delist rather than mark.

## Pagination trap — filler past the end

Beyond the last page glotr serves **21 unrelated products, a different set
every time**, under the category's own heading. "No new ids" never fires; a
240-oven category ingested 2,739. Stop when the pager's `<li class="next">`
has no `<a>` (last page is `next disabled`; past the end there is no
`pagination-list` at all). The pager is windowed (page 1 links 2–5 only);
never size the catalogue from it. Keep no-new-ids as a backstop.

Fixtures: `tests/fixtures/sources/glotr*.html`. Tests: `tests/sources/test_glotr.py`.
