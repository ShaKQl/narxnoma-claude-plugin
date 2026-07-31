# olcha.uz — REST GET, full-catalogue pull

Reference implementation: [`fill_olcha_prices.py`](../../fill_olcha_prices.py)

The only source fetched by **pulling the whole category once and matching locally**,
rather than one search per phone. That choice is what makes it efficient and gives it
the best coverage of the non-uzum sources.

---

## 1. Why catalogue, not search

olcha's search endpoint caps results per query, so 66 phones would mean 66 ranked,
truncated calls. The catalogue endpoint returns the *entire* smartphone category in
**~23 paged calls** (indicative, not fixed -- the catalogue grows) with no ranking
cap — fewer requests, complete data, and matching happens offline against the full
set.

Use this pattern whenever a site exposes a category listing and the category is small
enough (hundreds, not thousands). It is **not** viable on uzum or alifshop, where the
smartphone category runs to thousands of multi-seller listings.

## 2. Endpoint

```
GET https://mobile.olcha.uz/api/v2/products?page=<n>&per_page=20&category=telefony
```

No auth. Note the `mobile.` host — this is the mobile-app API.

```http
Accept: */*
Accept-Language: ru
clientmodel: web
Origin: https://olcha.uz
Referer: https://olcha.uz/
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36
```

`clientmodel: web` is required.

> **`per_page` is capped at 20 server-side.** Requesting 100 silently returns 20, so
> the page count is fixed by the category size (~460 phones → ~23 pages as observed
> in a live sweep on 2026-07-31; indicative, not fixed -- it drifts as the catalogue
> changes). Don't try to shortcut it.

## 3. Response shape

```jsonc
{
  "data": {
    "products": [
      {
        "name_ru": "Смартфон Samsung Galaxy A27 5G 8/256GB Pink",
        "discount_price": 3290000,   // current price, PLAIN SUM, arrives as an int
        "total_price": "3590000",    // pre-discount, arrives as a STRING
        "alias": "smartfon-samsung-galaxy-a27-5g-8-256gb-pink",
        "quantity": 12
      }
    ],
    "paginator": {"last_page": 23}
  }
}
```

| Field | Meaning |
|---|---|
| `discount_price` | **use this**; fall back to `total_price` when absent/0. Arrives as an **int**. |
| `total_price` | fallback only. Arrives as a **string**, not an int -- do not assume either field's type. |
| `name_ru` | carries RAM + storage + colour |
| `alias` | URL slug |
| `quantity` | stock |
| `paginator.last_page` | loop bound |

> **Both price fields must go through numeric coercion, never used raw.**
> `discount_price` and `total_price` are typed differently by the same
> endpoint on the same item -- a retailer changing a field's JSON type is
> invisible to a status-code check, and code that assumes an int is how a
> whole source silently yields nothing. This is why every price in this
> client passes through `coerce_price()` (`narxnoma/sources/base.py`)
> before a `Listing` is built.

## 4. Product URL — verified

```
https://olcha.uz/ru/product/view/<alias>
```

The intuitive `https://olcha.uz/ru/product/<alias>` **404s**. The `/view/` segment is
required. Discovered from a live category page and confirmed in a browser.

## 5. Fetch-and-cache

The catalogue changes slowly; a 24-hour cache makes reruns instant.

```python
CACHE_PATH = os.path.join("database", "cache", "olcha_telefony.json")
CACHE_TTL  = 24 * 3600

def fetch_catalog(session, refresh=False):
    if not refresh and os.path.exists(CACHE_PATH) \
            and time.time() - os.path.getmtime(CACHE_PATH) < CACHE_TTL:
        return json.load(open(CACHE_PATH, encoding="utf-8"))

    items, page, last_page = [], 1, 1
    while page <= last_page:
        r = session.get(OLCHA_API,
                        params={"page": page, "per_page": 20, "category": "telefony"},
                        timeout=(15, 90))
        data = (r.json() or {}).get("data") or {}
        for p in data.get("products", []):
            price = to_num(p.get("discount_price")) or to_num(p.get("total_price"))
            if not (price and p.get("name_ru") and p.get("alias")):
                continue
            items.append({"price": int(price), "name": p["name_ru"],
                          "url": PRODUCT_BASE.format(alias=p["alias"])})
        last_page = (data.get("paginator") or {}).get("last_page", 1)
        page += 1
        time.sleep(0.3)

    json.dump(items, open(CACHE_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    return items
```

## 6. Matching against a full catalogue

Because you score every phone against ~460 items (indicative, not fixed) rather than
a ranked top-20, ties are common — the catalogue contains both parent rows and
per-variant rows. **Break ties toward the cheapest**, since variation rows carry the
full spec and win on model tokens anyway:

```python
if sc > best_score or (sc == best_score and best and item["price"] < best["price"]):
    best_score, best = sc, item
```

## 7. Gotchas

- `category=telefony` is the slug for smartphones. Other categories use their own
  slugs — check a category page URL.
- Some rows are accessories that slipped into the category; the storage rule filters
  them out.
- Watch out for false alarms when auditing: a match that looks wrong (`A37 Gray`
  matching a `Green` listing) may be correct — the ecom name really is
  `"Samsung Galaxy A37 5G 8 128 GB Awesome Gray Green"`. Always check the raw name
  before "fixing" a matcher.

## 8. Result

**52/66 (79 %)**. Misses are genuine absence (Vivo Y31d isn't stocked; some colours
like Reddish Brown / Ocean Cyan and configs like Honor X5d Plus aren't carried) —
zero matcher failures.
