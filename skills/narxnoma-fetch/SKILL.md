---
name: narxnoma-fetch
description: Use when asked for electronics prices, listings or product data from Uzbek online retailers (uzum, alifshop, beemarket, idea, mediapark, olcha, texnomart, asaxiy, radius, glotr), or when running, extending or debugging the narxnoma crawler engine.
---

# narxnoma fetch engine

## Overview

Ten verified retailer clients behind one `Source` protocol, one `Listing`
contract, and a CLI that needs no database. Every client was rebuilt from the
notes in `docs/parsers/` and asserted live; the notes are canonical. When code
and doc disagree, verify live and fix both in one commit.

## Quick start (no Postgres)

```bash
pip install -e narxnoma-crawler          # Python >= 3.11; requests + psycopg only
cd narxnoma-crawler
python -m narxnoma.cli fetch --source olcha --limit 20              # sweep, JSON lines
python -m narxnoma.cli fetch --source uzum --category laptops        # default: smartphones
python -m narxnoma.cli fetch --source mediapark --query "iphone 16"  # search-only source
python -m narxnoma.cli fetch --source texnomart --raw > texnomart.jsonl
```

One `Listing` per line: `store_slug, source_key, name_raw, price (integer UZS),
url, availability (IN_STOCK|OUT_OF_STOCK|UNKNOWN), image_url, category`.
`--raw` appends the retailer's untouched payload. `fetch` is raw listings: a
search returns cases and other storage tiers too, so pick the variant by
`name_raw`; the matcher runs only in the Postgres pipeline (`cluster`). Exit 1 when a search-only
source is asked to sweep; never an empty stream that exits 0.

Categories: `smartphones televisions laptops acs fridges washers ovens`.

## Pick the source skill

| slug | kind | sweep | search | skill |
|---|---|---|---|---|
| uzum | GraphQL, anonymous self-minted token, multi-seller | yes | yes | fetch-uzum |
| alifshop | REST POST, multi-seller, price in **tiyin** | yes | yes | fetch-alifshop |
| beemarket | REST GET, category endpoint | yes | yes | fetch-beemarket |
| idea | REST GET, brand queries, no pagination | yes | yes | fetch-idea |
| mediapark | REST GET autocomplete, ~10 hits, **no sweep** | no | yes | fetch-mediapark |
| olcha | REST GET, full catalogue pull | yes | client-side | fetch-olcha |
| texnomart | REST GET, broad query `q=smartfon` | yes | yes | fetch-texnomart |
| asaxiy | server-rendered HTML, `/ru/` path | yes | no | fetch-asaxiy |
| radius | Saleor GraphQL, one row per variant | yes | yes | fetch-radius |
| glotr | server-rendered HTML classifieds, **robots.txt disallows** | by grant only | no | fetch-glotr |

Each source skill states the exact endpoint, headers, price field and unit,
URL rule, and the traps that silently produce wrong numbers.

## Rules every source obeys

1. **Never trust a slug you built yourself.** Open one built URL in a browser
   before trusting the column (alifshop `/moderated-offer/`, radius default-variant id).
2. **Verify the price against the rendered page**, not only the JSON (uzum card vs SKU).
3. **Search relevance is not precision.** Endpoints return cases, chargers and
   other storage tiers; the matcher decides, not the search engine.
4. **Broad query, strict match.** Strict-AND engines return zero on extra
   words; strip colour/`5G`/brand from the query, enforce them in the matcher.
5. **Price fences**: `100_000 <= price <= 100_000_000` UZS, else it is a unit
   bug (`narxnoma/sources/base.py`). Run every raw price through `coerce_price`.
6. **Be polite**: sequential requests, 0.3–0.6 s pause (`NARXNOMA_MIN_DELAY`/`MAX_DELAY`),
   real `User-Agent`, the `Origin`/`Referer` the site's own SPA sends.

## Engine layout

```
narxnoma-crawler/narxnoma/
  sources/<slug>.py   Source: slug, can_sweep, sweep(category), search(query)
  sources/base.py     Listing, coerce_price, try_build_listing, paginate
  sources/http.py     polite_session, get_json, get_text, post_json
  matching/           name -> (brand, model, memory, colour) identity, scoring
  pipeline/           harvest -> cluster -> aggregate -> report (Postgres)
  cli.py              fetch | harvest | cluster | aggregate | quality | report | cycle
tests/fixtures/sources/<slug>.json|html   recorded live responses, one per source
docs/parsers/<slug>.md                    canonical notes
```

With Postgres: `export NARXNOMA_DSN=postgresql://...` then
`python -m narxnoma.cli cycle` (see `docs/deployment/local-postgres.md`).

## Tests

```bash
cd narxnoma-crawler && python -m pytest -q            # fixture-backed, offline
python -m pytest -q -m live tests/sources/test_contract_live.py   # hits retailers
```

## Common mistakes

| Mistake | Reality |
|---|---|
| Scrape the HTML | Nine of ten sites are SPAs with an empty shell; call the JSON API the SPA calls. asaxiy and glotr are the exceptions. |
| Check HTTP status only | uzum and radius report GraphQL failure with **HTTP 200** and an `errors` key. |
| Use `minSellPrice` / `old_price` / `price` | Card, struck-through and list prices are not the offer price. Each skill names the one field. |
| Stop paging on an empty page | asaxiy redirects out-of-range pages to page 1; glotr serves unrelated filler forever. Stop on the site's own pager. |
| Treat count as correctness | A present-but-wrong image/URL keeps every count green. Read the id twice from two places and drop the row when they disagree. |

Adding a store: see skill `adding-a-narxnoma-source`.
