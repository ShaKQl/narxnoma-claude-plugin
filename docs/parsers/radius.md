# radius.uz — Saleor GraphQL, public and introspectable

Client: [`narxnoma/sources/radius.py`](../../narxnoma-crawler/narxnoma/sources/radius.py)

The ninth source, added 2026-08-11. Technically the cleanest of the nine and
the smallest by volume — and those two facts are unrelated to its value, which
is that it puts a **second price on 212 products**.

radius.uz runs [Saleor](https://saleor.io/). Its own front end talks to
`https://new.api.radius.uz/graphql/` anonymously: no token, no signing, no
per-brand search, and **introspection is enabled**, so the schema documents
itself. Every field we need is a typed column rather than a string to be
parsed.

---

## 1. Endpoint

```
POST https://new.api.radius.uz/graphql/
```

No auth.

```http
Accept: application/json
Content-Type: application/json
Accept-Language: ru
Origin: https://radius.uz
Referer: https://radius.uz/
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36
```

Found by reading their own JS bundles (`/_next/static/chunks/*.js`) for a
`radius.uz` host — the front end is server-rendered, so the call never appears
in the browser's network tab. `api.radius.uz` does not resolve; `new.api.` is
the live one. `GET` on the endpoint serves a GraphQL Playground.

The schema is Saleor's, so the [Saleor API
reference](https://docs.saleor.io/api-reference) applies to anything not
covered here.

## 2. The query

```graphql
query CategoryProducts($slug: String!, $first: Int!, $after: String) {
  category(slug: $slug) {
    slug
    products(first: $first, after: $after) {
      totalCount
      pageInfo { hasNextPage endCursor }
      edges { node {
        id name slug isAvailable
        brand { name }
        category { slug }
        defaultVariant { id }
        variants { id name sku priceAmount currency
                   isAvailable quantityAvailable thumbnail(size: 512) { url } }
        pricing { priceRange { start { amount currency } } }
        thumbnail(size: 512) { url }
      } }
    }
  }
}
```

`Category.products` **already includes descendant categories** — verified:
`konditsionery` reports `totalCount: 17`, which is exactly the sum of its five
brand children. So the sweep asks the parent and gets the brands for free.

Pagination is Saleor's cursor connection: pass `pageInfo.endCursor` back as
`after` while `hasNextPage` is true. There is no page number.

**`Money` here is flat.** `{ amount currency }`, not Saleor's usual
`{ gross { amount } }`. Querying `gross` fails the whole request with
`Cannot query field "gross" on type "Money"`.

## 3. The variant is the offer, not the product

**This is the one decision that matters on this source, and getting it wrong
costs almost the whole phone catalogue.**

radius keeps the product name generic and the identity on the variant:

| | |
|---|---|
| `Product.name` | `Samsung Galaxy A26` |
| `Variant.name` | `Смартфон Samsung Galaxy A26 5G 8/256GB Black (Черный)` |

A phone key needs the memory pair and the colour, and the product name has
neither. Measured: emitting one listing per `Product` attached **1 of 80
phones (1.3%)**. Emitting one per `ProductVariant` attached **168 of 169
(99.4%)**.

Non-phones attached at 100% either way — which is exactly why this had to be
read per category rather than trusted as an average. A single headline
attachment rate would have hidden it.

Each variant also carries its own `priceAmount`, its own stock and its own
working URL, so this is not a modelling preference — a per-product parser
publishes one of "HUAWEI Nova Y61"'s three prices (1,397,000 … 1,959,000) as
the price of all three.

| Field | Meaning |
|---|---|
| `variant.id` | **the source key** (decoded, see §4) |
| `variant.name` | **use this for the product name** — carries memory and colour |
| `variant.priceAmount` | **use this** — plain UZS as a float |
| `variant.isAvailable` | stock; falls back to `product.isAvailable` |
| `variant.sku` | the manufacturer code, e.g. `ARTSID2CW12BE` |
| `product.slug` | the URL slug (see §5) |

## 4. Ids are base64 global ids

Saleor returns `id` as base64 `"<Type>:<number>"`:

```
UHJvZHVjdDo1MTk1              -> Product:5195
UHJvZHVjdFZhcmlhbnQ6ODA0Ng==  -> ProductVariant:8046
```

Decode to the number. A malformed id must cost one listing, not the sweep, so
the decoder returns `None` rather than raising.

## 5. The product URL uses the DEFAULT VARIANT id — not the product id

```
https://radius.uz/ru/product/<variant-id>-<product-slug>
```

This is the trap [README rule 1](README.md) exists for. Both ids sit next to
the slug in the payload and both are plausible integers, but:

```
/ru/product/5195-konditsioner-artel-artsid2cw12be-iceberg-inv   404   (product id)
/ru/product/8046-konditsioner-artel-artsid2cw12be-iceberg-inv   200   (variant id)
```

Checked on six products: **every product-id URL 404s.** Verified further that
a *non-default* variant's id also resolves and renders that specific colour,
which is what makes the per-variant URL in §3 legitimate rather than a guess.

## 6. Category slugs — and the Apple trap

Verified live 2026-08-11 by walking the whole tree through
`categories(first: 100, level: 0)` and reading every `totalCount`.

| Our category | radius slugs | Products |
|---|---|---:|
| `smartphones` | `smartfony`, `iphone-17-17-pro-17-pro-max-air`, `iphone-air-3` | 84 |
| `fridges` | `kholodilniki` | 22 |
| `televisions` | `televizory` | 18 |
| `acs` | `konditsionery` | 17 |
| `washers` | `stiralnye-mashiny` | 17 |
| `laptops` | `noutbuki`, `noutbuki-apple` | 16 |
| `ovens` | `gazovye-plity`, `dukhovoi-shkaf` | 13 |

**Not every category hangs where its name suggests.** `noutbuki` holds 9
laptops and not one is an Apple: the 7 MacBooks sit under a top-level **Apple**
category, as do the iPhones, which are absent from `smartfony` entirely.
Sweeping the obvious slug alone silently loses every Apple product — including
the iPhones, the most-compared phones in the catalogue — and the loss looks
exactly like a retailer that stopped stocking them.

The Apple entries are the fragile ones: they are marketing buckets
(`🆕 iPhone 17 | 17 Pro | 17 Pro Max`), renamed as lines launch. There is no
stable "Смартфоны Apple" node. `test_radius_categories.py` pins this map.

Deliberately not swept: `mikrovolnovye-pechi` (9) and `mini-pechi` (8) — the
same decision as [asaxiy](asaxiy.md#5-category-leaves), for the same measured
reason: all 540 `ovens` offers the other sources contribute contain no
microwave, so these could never price-compare.

## 7. GraphQL reports failure with HTTP 200

Same trap as [uzum](uzum.md): an `errors` key beside a `null` `data`, under a
200 status. The client raises on `errors` and on a null `category`, because
swallowing either would record a half-swept category as a successful harvest
of nothing — the one failure mode `EXPECTED_MIN_OFFERS` and `harvest_run.ok`
exist to catch.

## 8. Measured result

274 offers, **98.9% of them attached** to a canonical product.

| Category | Offers | Attached |
|---|---:|---:|
| smartphones | 169 | 99.4% |
| fridges | 22 | 100% |
| televisions | 18 | 100% |
| washers | 17 | 100% |
| acs | 17 | 100% |
| laptops | 17 | 88.2% |
| ovens | 14 | 100% |

**212 of its products are carried by at least one other store, and 54 of them
had only one price before radius arrived.** That is the number a small source
is worth judging on: radius adds 2.2% of the catalogue's offers and 4.8% of
its comparisons.

Its prices sit consistently at the top of the range (it sells on instalment
terms), which is itself useful — a comparison needs both ends.

All 212 multi-store variants were read offer by offer. Every merge is correct,
matched on catalogue codes: `ARTSIQ3BW12BE`, `ARTSID3AW12BE`, `AVLSIQ1AW12BE`.

---

## 9. TRAP — a thumbnail URL for a thumbnail that was never rendered

Saleor returns a `thumbnail(size: N) { url }` for every image, and the field is
non-null and well-formed regardless of whether the file exists. radius's
thumbnailer does not render `.avif` sources: the URL 404s with
`application/xml`.

Sampled across all 274 live radius offers:

| extension | count | thumbnail status |
|---|---|---|
| `.webp` | 218 | 200 |
| `.jpg` | 31 | 200 |
| `.png` | 23 | 200 |
| `.avif` | 2 | **404** |

The original **does** exist — the same path with `/thumbnails/<N>/` replaced by
`/media/` returns `200 image/avif` — so that is what we publish for those two.
Only for avif: `/thumbnails/` is the right thing to hotlink into a grid
everywhere it works, and swapping wholesale would serve full-size originals for
272 products to fix 2.

Worth stating plainly because no upstream check can catch it: "the field is
present" and "the file exists" are different questions, and only the second one
matters to a page that renders the URL.
