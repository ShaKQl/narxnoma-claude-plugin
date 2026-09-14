---
name: fetch-uzum
description: Use when fetching prices or listings from uzum.uz (Uzum Market), minting its anonymous GraphQL token, or when an uzum request returns 401, HTTP 200 with an errors key, or prices that do not match the product page.
---

# uzum.uz — GraphQL, anonymous token, multi-seller

Largest source (5,000+ offers). Only source with auth, per-SKU pricing, and a
failure mode that looks like success. Full notes: `docs/parsers/uzum.md`.
Client: `narxnoma-crawler/narxnoma/sources/uzum.py`.

## Run

```bash
cd narxnoma-crawler   # pip install -e . once
python -m narxnoma.cli fetch --source uzum --category smartphones --limit 50
python -m narxnoma.cli fetch --source uzum --query "galaxy a56"
```

## Auth — mint, no account

```
POST https://id.uzum.uz/api/auth/token   body {}
Accept-Language: ru-RU        # required (any value)
Referer: https://uzum.uz/     # required (uzum.uz origin)
```

Response **204 No Content**; token is in `Set-Cookie: access_token=<JWT>`, not
the body. `Origin` is NOT required. TTL 6 h (`exp` claim); refresh ~5 min early.
A bare 401 mid-run means server-side revocation: re-mint once, retry once.

## Endpoint

```
POST https://graphql.uzum.uz/
Authorization: Bearer <token>
Content-Type: application/json
apollographql-client-name: web-customers
x-iid: <any UUID>
```

All four required. Drop `apollographql-client-name` or `x-iid` and you get
**HTTP 200, `data: null`, `errors: [...]`**. Always inspect `errors`.
Introspection is on; persisted queries not enforced. Query text: `SEARCH_QUERY`
in the client; pagination `offset`/`limit` (72 per page, offset cap 1000, so the
frontier is per category, not per brand).

## Price — SKU, never card

| field | meaning | use |
|---|---|---|
| `skuList[].sellPrice` | this variant's price, integer UZS | **yes** |
| `minSellPrice` | card minimum across every model and tier | no |
| `fullPrice` | struck-through pre-discount | no |

One listing per SKU. Card titles are marketing blurbs bundling several models;
memory and colour come from SKU `characteristics`, whose keys are typo-ridden
(`Объем встроенной памяти` vs `Объём ...`) — match by token `ram`/`rom`, not by
exact key. Category filter client-side on `catalogCard.category.id`
(15271 Android, 15272 iPhone; other categories in `CATEGORY_IDS`).

## URL

`https://uzum.uz/ru/product/<productId>?skuId=<skuId>` — 302s to the slug URL;
never build a slug. `?skuId=` preselects the exact variant.

## Images

Request `photos` explicitly; it is not in the default selection. Missing it
published 5,461 offers with no picture while every count stayed green.

## Traps

- eSIM-only variants carry a marker; an unmarked phone is dual-SIM, not unknown.
- Colours in characteristics are Russian; in card/model strings often Uzbek
  (`Kumush`, `Tilla`, `Yashil`, `Muz`). Both vocabularies in the matcher.
- Search is strict AND: drop colour words and `5G`/`4G` from the query.
- Multi-seller: many partners per SKU. Price = IQR-trimmed median; uzum also
  reports a min.

Fixture: `tests/fixtures/sources/uzum.json`, `uzum_photos.json`. Tests: `tests/sources/test_uzum*.py`.
