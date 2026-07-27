# uzum.uz — GraphQL, multi-seller

Reference implementation: [`fill_uzum_prices.py`](../../fill_uzum_prices.py)

The largest marketplace in Uzbekistan and the richest data source here — it is the
only one that exposes **per-variant (SKU) price, stock and characteristics**, rather
than a single price attached to a name string.

It is also the only one with auth, and the only one where a naive implementation
returns **plausible but wrong numbers**. Read the two trap sections before writing code.

---

## 1. Auth — anonymous, self-minting

`graphql.uzum.uz` returns a bare **401 with an empty body** without a Bearer token.
The token requires no account:

```
POST https://id.uzum.uz/api/auth/token
Accept-Language: ru-RU
Referer: https://uzum.uz/
Body: {}
```

Response is **`204 No Content`** — the token is **not in the body**, it arrives as a
`Set-Cookie: access_token=<JWT>` header (a `refresh_token` is also set, on
`.id.uzum.uz`). This is why an early probe looked like it returned nothing.

TTL **6 hours** (`exp` in the JWT payload), no login, no captcha. Mint a fresh one
per run and refresh ~5 min before `exp`.

### Exactly two headers are required (measured by ablation)

| Header | Required | Omitting it gives |
|---|---|---|
| `Accept-Language` | **yes** (any value: `ru-RU`, `ru`, `en-US` all work) | `400 {"baseError":{"code":"insufficient_headers"}}` |
| `Referer` | **yes**, must be on the `uzum.uz` origin (any path) | `400 {"baseError":{"code":"unallowed_app"}}` |
| `Origin` | no — mints fine without it | — |
| `Accept`, `Content-Type`, `User-Agent`, `x-iid` | no | — |

A foreign `Referer` (e.g. `https://example.com/`) is rejected with `unallowed_app`,
so this is a soft origin check keyed on Referer rather than Origin. Send both plus a
real UA anyway to stay indistinguishable from the site's own traffic.

```python
import uuid, json, base64, requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")

def mint():
    iid = str(uuid.uuid4())
    s = requests.Session()
    s.post("https://id.uzum.uz/api/auth/token",
           headers={"Accept": "*/*", "Accept-Language": "ru-RU",   # required
                    "Content-Type": "application/json",
                    "Origin": "https://uzum.uz",
                    "Referer": "https://uzum.uz/",                 # required
                    "User-Agent": UA, "x-iid": iid},
           json={}, timeout=25)
    token = next(c.value for c in s.cookies if c.name == "access_token")
    p = token.split(".")[1]; p += "=" * (-len(p) % 4)
    exp = json.loads(base64.urlsafe_b64decode(p))["exp"]
    return s, token, iid, exp
```

## 2. The endpoint

```
POST https://graphql.uzum.uz/
```

Required set, measured by ablation — **four headers**, and two of them are
non-obvious:

| Header | Value | Required |
|---|---|---|
| `Authorization` | `Bearer <token>` | **yes** — bare `401` without |
| `Content-Type` | `application/json` | **yes** |
| `apollographql-client-name` | `web-customers` | **yes** — see below |
| `x-iid` | any UUID (install id) | **yes** — see below |
| `apollographql-client-version` | `1.63.2` | no |
| `city-id` | `1` (Tashkent) | no, but affects stock/delivery |
| `city-latitude` / `city-longitude` | `41.379112` / `69.29944` | no |
| `Origin` / `Referer` / `Accept` / `Accept-Language` / `User-Agent` | — | no |

> **Failure mode you must handle: it does not fail with an HTTP error.**
> Drop `apollographql-client-name` or `x-iid` and the request still returns
> **`200 OK`**, with `data: null` and:
> ```json
> {"errors": [{"message": "HTTP fetch failed from 'search-gateway': 4.."}]}
> ```
> Checking `response.status_code` alone will report success on a request that
> returned nothing. **Always inspect the `errors` key.** This is also true of the
> valid-query-but-null case:
> `{"extensions":{"valueCompletion":[{"message":"Cannot return null for non-nullable field Query.makeSearch"}]}}`
> — which is what a stale variables shape looks like.

Minimal working request: `Authorization` + `Content-Type` +
`apollographql-client-name` + `x-iid`. Send the full browser-like set anyway.

### Persisted queries are NOT enforced

The browser sends an Apollo **persisted query** — a `sha256Hash` instead of query
text, which is why the captured request body is only ~322 bytes. That normally
implies a server-side safelist. **It is not enforced here**: sending full query text
works fine. You do not need to extract hashes.

### Introspection is ON — use it, don't copy old scrapers

```graphql
{ __schema { queryType { name fields { name } } } }
```

works and returns 49 root queries / 428 types. **The query shape used by every
public uzum scraper is stale** — `SortType`, `SearchFilterInput`, and the old
`MakeSearchQueryInput` fields no longer exist. If the schema changes again,
re-introspect rather than guessing:

```graphql
{ __type(name: "MakeSearchQueryInput") {
    inputFields { name type { kind name ofType { kind name } } } } }
```

Note: this server rejects `__type(name: $var)` with a **variable** — inline the
string literal.

## 3. The search query (current, verified)

```graphql
query getMakeSearch($q: MakeSearchQueryInput!) {
  makeSearch(query: $q) {
    total
    items {
      catalogCard {
        __typename
        productId
        title
        category { id title }
        ... on SkuGroupCard {
          skuList {
            id
            sellPrice
            fullPrice
            availableAmount
            characteristicValues { title characteristic { title } }
          }
        }
      }
    }
  }
}
```

Variables:

```json
{"q": {
  "text": "Samsung Galaxy A17 6 128",
  "showAdultContent": "TRUE",
  "filters": [],
  "sort": "BY_RELEVANCE_DESC",
  "pagination": {"offset": 0, "limit": 72}
}}
```

`MakeSearchQueryInput` — required: `showAdultContent`, `filters`, `sort`,
`pagination`. Optional and useful: `categoryId`, `correctQuery`, `getFastCategories`,
`getFastFacets`, `showOnlyOriginalSKUs`.

- `Sort` enum: `BY_RELEVANCE_DESC`, `BY_PRICE_ASC`, `BY_PRICE_DESC`,
  `BY_RATING_*`, `BY_DATE_ADDED_*`, `BY_ORDERS_NUMBER_*`
- `ShowAdultContent` enum: `NONE`, `FALSE`, `TRUE`
- `CatalogCard` is an **interface** implemented by `ProductCard`, `SkuGroupCard`,
  `SkuCard` — `skuList` only exists on the concrete types, hence the inline fragment.

**Pagination caps at `offset` ≈ 1000** (beyond that `items` comes back empty).
`limit` is honoured generously — 72 is a good value, giving ~100 phone SKUs per call.
Per-query search is the right approach; a full-catalogue pull like olcha's is
infeasible because the Android smartphone category runs to thousands of multi-seller
listings.

### Category filter

Relevance search mixes in cases, chargers and (genuinely) vacuum cleaners. Filter
client-side on the card's `category.id`:

| id | title |
|---|---|
| `15271` | Смартфоны Android |
| `15272` | Смартфоны Apple iPhone (iOS) |

`showOnlyOriginalSKUs: "TRUE"` narrows 262 → 60 results but does **not** cleanly
strip grey-market resellers (the "IMEI зарегистрированы" cards survive it). Not a
useful lever — skip it.

## 4. Response shape

```jsonc
{"data": {"makeSearch": {
  "total": 262,
  "items": [
    {"catalogCard": {
      "__typename": "SkuGroupCard",
      "productId": 1983388,
      "title": "IPhone 17 Pro/Pro Max, 256, 512 , 1 ТБ , 2 ТБ / Оба IMEI зарегистрированы",
      "category": {"id": 15272, "title": "Смартфоны Apple iPhone (iOS)"},
      "skuList": [
        {"id": 7028608, "sellPrice": 20789010, "fullPrice": 31000000,
         "availableAmount": 27,
         "characteristicValues": [
           {"title": "17 Pro Max 256 GB", "characteristic": {"title": "Модель"}},
           {"title": "Серебряный",        "characteristic": {"title": "Цвет"}}]}
      ]}}
  ]}}}
```

- **Price field: `skuList[].sellPrice`** — plain SUM integer, discount already applied.
  `fullPrice` is the struck-through pre-discount price and is often fantasy
  (`31,000,000` above) — never use it.
- `availableAmount` — filter to `> 0`; zero-stock SKUs are phantom listings.
- Card-level `minSellPrice` / `minFullPrice` also exist. **Do not use them** — see below.

## 5. TRAP 1 — card price ≠ product price

Uzum resellers bundle **several models and every storage tier under one card**:

```
"IPhone 17 Pro/Pro Max, 256, 512, 1 ТБ, 2 ТБ"    minSellPrice = 16,985,000
    ├ 17 Pro 256 GB          19,106,010
    ├ 17 Pro Max 256 GB      20,789,010   ← the one we actually sell
    ├ 17 Pro Max 512 GB      24,483,000
    └ 17 Pro Max 1 TB        39,999,000
```

`minSellPrice` — the obvious field, and the one every naive scraper reads — is the
cheapest variant *on the card*. For a 17 Pro Max 256 it understates by **~3.8 M**.

**Match at SKU level.** Build the candidate string from the SKU's own
`characteristicValues`, and use the card title only for brand context.

### 5a. Card titles are marketing blurbs

`"Смартфон Samsung Galaxy A17, 6.7\" Super AMOLED 90Гц экран, камера 50Мп, 5000 мАч"`
— those stray numbers become model tokens and reject every real match. Take the card
title only **up to its first comma**, and let the SKU's `Модель` characteristic
override it entirely when present.

### 5b. The same trap for memory — subtle and costly

```
card title:  "…Samsung Galaxy A17 4G 8/256GB"   ← the card's overall range
sku Память:  "6/128GB"                          ← what THIS sku actually is
```

Concatenating both lets the title's `8/256` satisfy an 8/256 target while the SKU is
really a 6/128 — it reported **2,672,010** for a phone whose true price was
**3,068,010**. When the SKU states its own memory, strip memory figures from the
title before concatenating:

```python
if mem_v:  # sku stated its own memory → it wins outright
    spec = re.sub(r"(?<![a-zа-я])\d{1,4}\s*(?:gb|гб|tb|тб)?\s*[/\\+|]\s*"
                  r"\d{1,4}\s*(?:gb|гб|tb|тб)?", " ", spec, flags=re.I)
    spec = re.sub(r"(?<![a-zа-я\d])\d{1,4}\s*(?:gb|гб|tb|тб)\b", " ", spec, flags=re.I)
```

## 6. TRAP 2 — eSIM-only variants

Our iPhones are **nanoSIM + eSIM**. Uzum lists eSIM-only variants side by side at a
materially lower price:

| variant | price |
|---|---|
| 17 Pro Max 256 GB (dual) | 20,789,010 |
| 17 Pro Max 256 (e-Sim) | 19,453,000 |
| 17 Pro Max 256GB (eSIM) | 18,099,000 |

Encoded **three different ways** — all must be screened:

1. `Модель: "17 Pro Max 256 (e-Sim)"` or `"iPhone 17 Pro Max 256GB (eSIM)"`
2. a SIM characteristic (`Сим-карта`, `SIM карта`, ` SIM карта`) with value
   `e-SIM` / `ESIM` — the physical variant reads `SIM`
3. the **card title** itself, e.g. `"Apple смартфон iPhone 17 Air 256GB, 512GB, 1TB, eSIM"`

Explicit dual markers (`SIM+eSIM`, `nanoSIM+eSIM`, `2 SIM`, `dual`) must **not** be
rejected — check them first. The dual marker appears with `+`, `/` and `-`
separators (`SIM+eSIM` in the raw characteristic value, `nano-SIM/eSIM` on the
rendered spec sheet), so all of them — plus whitespace, `_` and `.` — are
stripped before matching, collapsing every spelling onto one canonical form:

```python
_SEPARATORS = re.compile(r"[\s_.\-/+]")
_DUAL = re.compile(r"simesim|dual|2sim|двесим")
_ESIM = re.compile(r"esim")

def is_esim_only(text):
    low = _SEPARATORS.sub("", str(text).lower())
    if _DUAL.search(low):
        return False
    return bool(_ESIM.search(low))
```

`_DUAL` matches a **bare `dual`**, not just `dualsim`. The marker list above names
`dual` on its own, but the pattern used to require the compound spelling, so
`sim_kind("dual")` returned `"unknown"` — a phone explicitly documented as dual came
back unclassified. The bare alternative subsumes `dualsim`, so that spelling no longer
needs its own branch.

Verify on the rendered page: the product spec sheet shows
`Тип SIM карты : nano-SIM/eSIM` for the dual variant.

### An unmarked phone is dual, not unknown

Because eSIM-only variants are **always** explicitly marked — in all three encodings
above — silence carries information: an unmarked phone is the ordinary dual-SIM one.
`variant_key` therefore normalises `sim_kind="unknown"` to `"dual"` before building the
key.

This is also what keeps `slug()` injective. `slug()` only appends a suffix for
`esim_only`, so `"unknown"` and `"dual"` built two *different* `VariantKey`s that
rendered to the *identical* slug — two canonical products claiming one URL, with
whichever wrote last silently winning. Normalising at key construction collapses them
into the one product they always were. `esim_only` keeps its distinguishing `-esim`
suffix.

`SIM_KINDS` is enforced, not merely declared: `variant_key` raises `ValueError` on
anything outside `("dual", "esim_only", "unknown")`. Without the check a typo such as
`"Dual"` or `"dual_sim"` became part of a canonical identity and minted a second
product for a phone that already had one.

Note the normalisation is deliberately **not** applied to `partial_key`: there,
`"unknown"` still means "not yet known" and is what lets `resolve_partial` match a
partial offer against either SIM variant before refusing on ambiguity.

## 7. Characteristic keys are a typo minefield

Never match characteristic keys exactly. Observed across 66 queries:

`Цвет` · `Память` · `память` · `ПАМЯТЬ` · `Памят:` · `Память:` · `Памяьт:` ·
`памяять` · `Память ` · `Объем памяти` · `Xotirasi` (Uzbek) · `RAM/ROM` · `Модель` ·
`модел` · `Сим-карта` · `SIM карта` · ` SIM карта` (leading space) · `Тип` ·
`16 PRO MAX` (a value used as a key)

Classify loosely by prefix:

```python
def char_kind(key):
    k = normalize(key)
    if k.startswith("памя") or k.startswith("xotira") or "объем памяти" in k:
        return "memory"
    if k.startswith("модел"):           return "model"
    if "sim" in k or "сим" in k:        return "sim"
    if k.startswith("цвет") or k.startswith("rang"): return "color"
    return "other"
```

## 8. Colours are Russian — and, in card/model strings, Uzbek

> **Corrected 2026-07-26.** The heading used to read "Russian only". That holds for the
> **`Цвет` characteristic**, but *not* for card titles and `Модель` values, which are
> frequently Uzbek: `Smartfon HONOR X7d 6/128GB Tilla`, `Honor X7d 6/128GB Kumush rang`,
> `HONOR X6c smartfoni 6/128 GB Muz`. Because §5 builds the candidate string from the
> card title when the SKU states no `Цвет`, those Uzbek words reach the matcher — and an
> unresolvable colour **rejects** (see below), so every one of them was a silent miss.
> Adding the Uzbek vocabulary took a 20-target benchmark from **5/20 to 15/20 matched**.

```python
UZ_COLORS = {
    "qora": "black", "oq": "white", "kumush": "silver", "kulrang": "gray",
    "tilla": "gold", "oltin": "gold", "sariq": "yellow", "yashil": "green",
    "kok": "blue", "ko'k": "blue", "moviy": "blue", "muz": "blue",
    "binafsha": "purple", "pushti": "pink", "qizil": "red",
    "jigarrang": "brown", "bej": "beige",
}
```

`rang` means "colour", not a colour — put it in `NON_MODEL_TOKENS` or `Kumush rang`
leaves a stray `rang` model token. Same for the listing filler `smartfoni`, `telefon`,
`zarbaga`, `chidamli`. Uzbek qualifiers `to'q` (dark) and `och` (light) must stay
**unmapped**, exactly like `тёмно` / `светло`.

### The `Цвет` characteristic itself

`Цвет` values are always Russian, so an English colour map is useless. All 33 values
observed: Черный, Серый, Тёмно-серый, Серый металлик, Серый меланж, Угольный,
Темно-синий, Синий, Синий меланж, Светло-синий, Голубой, Небесно-голубой, Ледяной,
Бирюзовый, Фиолетовый, Лавандовый, Сиреневый, Серебряный, Зеленый, Тёмно-зелёный,
Мятный, Оранжевый, Манго, Золотой, Песочный, Бежевый, Белый, Молочный, Кремовый,
Бордовый, Коричневый, Алый, Черное стекло.

Map at **token** level after normalising `ё → е` and stripping punctuation, so
`Тёмно-серый` → `{темно, серый}` → gray. Leave qualifier tokens (`тёмно`, `светло`,
`небесно`, `металлик`, `меланж`) unmapped — the base colour word is always present.

**An unmapped colour must reject, not pass.** If a candidate has a `Цвет` value you
cannot resolve, drop it for any colour-bearing target. Treating it as a wildcard let
`Конфетный` (candy) and `Хром` match *both* the Awesome Gray and Awesome Navy targets
simultaneously.

## 9. Product URL

```
https://uzum.uz/ru/product/<productId>?skuId=<skuId>
```

`302`-redirects to the canonical slug URL, so **no slug construction is needed** —
`/ru/product/2996442` lands on `/ru/product/smartfon-samsung-galaxy-2996442`.
`?skuId=` pre-selects the exact variant, which is what makes the link verifiable.

## 10. Query building

Uzum's search is strict AND. Drop colour words **and `5G`/`4G`** from the query —
many seller titles omit the band (`"Samsung Galaxy A37 8/256GB Gray Green"`), so
keeping it silently excludes real listings. Restore precision in the matcher, which
treats `5g`/`4g` as reserved and never scores on them.

Two-shot strategy: broad query first (no colour, no band), then the verbatim name as
a fallback; dedupe candidates by `skuId`.

## 11. Metrics produced

Multi-seller, so a single number hides the spread. Two columns:

- **`uzum min`** — cheapest matching in-stock SKU
- **`uzum median (IQR)`** — median of matching SKUs after IQR stripping

Links sheet gets both URLs (median link = the SKU whose price is nearest the median).
A large min↔median gap is genuine grey-market spread, not an error — Redmi A5 3/64
had sellers at 1.45 M and 3.0 M.

## 12. Result

**61/66 (92 %)** — best of all seven sources. The 5 misses were each verified as
genuine absence: Honor 400 12/256 (uzum stocks only 8/256 and 12/512) and Vivo Y31d
×4 (not listed at all).
