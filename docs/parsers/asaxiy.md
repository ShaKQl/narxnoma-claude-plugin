# asaxiy.uz — server-rendered HTML, no JSON API at all

Client: [`narxnoma/sources/asaxiy.py`](../../narxnoma-crawler/narxnoma/sources/asaxiy.py)

The eighth source, added 2026-08-10, and the one that breaks this directory's
opening rule.

> [README.md](README.md): *"None of these sites can be scraped from HTML — every
> one is a JavaScript SPA that renders an empty shell. The durable path is
> always the private JSON API the SPA itself calls."*

For asaxiy the durable path is the inverse, and it is not a preference. **There
is no catalogue JSON endpoint.** Probed live: the only `/ajax/*` routes the
site's own frontend calls are `check-phone`, `login-validate`,
`send-verification-sms` and `new-filter-url` — account and filter plumbing.
The category page returns a complete, fully-priced product grid in the initial
HTML document, and the "show more" button re-requests that same URL.

Broad-range retailer (books, toys, groceries) with a real electronics range.
Second-cheapest source to crawl after olcha: 34 requests for the whole
seven-category sweep.

---

## 1. Endpoint

```
GET https://asaxiy.uz/ru/product/<category-path>            # page 1
GET https://asaxiy.uz/ru/product/<category-path>/page=<N>   # page N ≥ 2
```

No auth, no cookies, no token.

```http
Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8
Accept-Language: ru-RU,ru;q=0.9
Origin: https://asaxiy.uz
Referer: https://asaxiy.uz/
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36
```

**The page number is a PATH segment, not a query parameter.** `?page=2` is
ignored; `/page=2` is what asaxiy's own pagination links and its "load more"
button use.

## 2. Language: `/ru/`, not a cookie and not a header

asaxiy defaults to Uzbek (`<html lang="uz">`). Three ways to ask for Russian
were tried:

| Attempt | Result |
|---|---|
| `Accept-Language: ru-RU,ru;q=0.9` | ignored — titles stay Uzbek |
| `_language=ru` cookie, set by hand | ignored (the cookie is Yii-signed) |
| `_language` cookie obtained from the server | sets the chrome; **titles stay Uzbek** |
| `?language=ru` | works — by **301-redirecting to `/ru/product/...`** |
| `GET /ru/product/...` directly | works, no redirect, stateless ✅ |

So the client requests the `/ru/` path. Note the trap in the fourth row:
`?language=ru` combined with `X-Requested-With: XMLHttpRequest` returns a bare
301 that `requests` does not follow, and you get an empty body.

**Do not depend on the path alone anyway** — see §3, every card states its
Russian name in an attribute regardless of which language the page rendered.

## 3. The card, and what to read from it

Product cards start at `<div class="product__item ">`. Do not parse the
rendered price text (`6 719 000 so'm`) or the title span. Every card carries
the hidden block asaxiy's own add-to-cart reads:

```html
<span id="product_cart_data_71120"
      data-id="71120"
      data-name="Стиральная машина 7TECH 7WM4S1060GSS1 6 Кг. ХИТ ПРОДАЖ!"
      data-name-ru="Стиральная машина 7TECH 7WM4S1060GSS1 6 Кг. ХИТ ПРОДАЖ!"
      data-price="2739000"
      data-old-price="0"
      data-img="https://assets.asaxiy.uz/product/main_image/mobile/68d7ac8f1d42b.png.webp"
      data-cart-id="84417387bc832ab2a76535d990ce2675"
      data-brand-name="7TECH"
      hidden>
```

| Field | Meaning |
|---|---|
| `data-id` | **the source key.** Also appears as `data-product-id` on the card's buttons |
| `data-price` | **use this** — plain SUM, no separators, already discounted |
| `data-old-price` | struck-through pre-discount price; `0` when there is no discount |
| `data-name-ru` | **use this for the product name** — present even on an Uzbek page |
| `data-name` | the name in the page's own language |
| `data-img` | absolute image URL |
| `data-brand-name` | the retailer's own brand string, e.g. `"Samsung"` |

`data-price` equals the outer div's `data-actual-price` on every card
observed, discounted or not.

### 3a. The URL must be tied to the product id

The card's anchor is:

```html
<a href="/ru/product/stiralnaya-mashina-7tech-7wm4s1060gss1-6-kg"
   onclick="sendSelectItemEvent(71120, this)">
```

Splitting an HTML document on a class name is only safe if nothing downstream
trusts the split alone. **Require `sendSelectItemEvent(<id>` to name the same
id as the cart block**, and drop the card otherwise. Without that check, a
change to asaxiy's card markup hands a product its neighbour's URL — a wrong
link that no price check, no key check and no aggregate metric can notice.

The href is localised: `/product/<slug>` on the Uzbek page, `/ru/product/<slug>`
on the Russian one. Store it as given, so the stored link opens in the language
the sweep read.

### 3b. Availability: read the CSS class, not the href and not the text

An in-stock card renders the buy control; an out-of-stock one renders
`<div class="h6">● Нет в наличии</div>` instead.

Measured on the whole washers category (144 cards): 132 carried the control,
12 did not, and those 12 were exactly the 12 carrying the out-of-stock text.
No card had both; none had neither.

Use **`js-buy-guest`**, the class asaxiy's own JavaScript binds to. Both
alternatives are localised and both will silently lie:

- the button's href is `/cart/simple?slug=` on the Uzbek page and
  `/ru/cart/simple?slug=` on the Russian one — reading it scored **every**
  Russian card out-of-stock, while looking entirely reasonable;
- `Нет в наличии` is Russian-only.

## 4. Pagination: an out-of-range page serves page 1

**This is the trap on this site.** `stiralnye-mashiny/page=9` of a 6-page
category does not 404 and does not return an empty grid. It
**301-redirects to page 1 and serves 24 real products again.** A client that
stopped on "an empty page" would loop until `MAX_PAGES` re-ingesting page 1
and record a triumphant harvest of duplicates.

The end of the catalogue is stated by each page in its own inline script:

```js
let totalPages = parseInt('6', 10) || 1;
```

The client stops on that **and**, independently, on the first page that
contributes no product id it has not already seen.

### 4a. Do not use the lighter XHR fragment

Sending `X-Requested-With: XMLHttpRequest` returns the bare product grid,
~310 KB instead of ~800 KB. It also drops the `totalPages` script — the only
end-of-catalogue signal there is, against the paginator described above.
Trading the stop condition for bandwidth is not a trade. The largest swept
category is 10 pages.

## 5. Category leaves

Verified live 2026-08-10 by walking the site's own category tree.

| Our category | asaxiy leaf path | Items | Pages |
|---|---|---:|---:|
| `smartphones` | `telefony-i-gadzhety/telefony/smartfony` | 233 | 10 |
| `televisions` | `televizory-video-i-audio/televizory` | 57 | 3 |
| `laptops` | `kompyutery-i-orgtehnika/noutbuki/noutbuki-2` | 90 | 4 |
| `acs` | `klimaticheskaya-tehnika/kondicionery` | 113 | 5 |
| `fridges` | `bytovaya-tehnika/krupnaya-tehnika-dlya-kuhni/holodilniki` | 107 | 5 |
| `washers` | `bytovaya-tehnika/tehnika-dlya-doma-2/stiralnye-mashiny` | 132 | 6 |
| `ovens` | `bytovaya-tehnika/krupnaya-tehnika-dlya-kuhni/gazovye-plity` | 18 | 1 |

Leaves deliberately **not** swept, each checked rather than assumed:

- **`kuhnya/mikrovolnovye-i-duhovye-pechi`** reads like the oven category and
  is not one. All 120 of its listings were read: 91 microwaves, 29 mini-ovens,
  **zero built-in ovens**. All 540 `ovens` offers the other six sources
  contribute contain no microwave at all, so these could never price-compare
  and every one would render under the "Духовой шкаф" label. asaxiy does not
  sell built-in ovens.
- **`kuhnya/nastolnye-plity`** — 3 items, tabletop hotplates (Sonifer SF-3050,
  BQ HP124SS). A countertop hob is not the freestanding cooker the other
  sources file under `ovens`.
- **`kompyutery-i-orgtehnika/noutbuki`** (the parent) carries laptop bags,
  stands, docks and chargers as siblings of the machines. `noutbuki-2` is the
  leaf that holds only laptops.

## 6. A category leaf is broader than the category

asaxiy's leaves mix in things that are not the product, and unlike a stray
search result these **form keys**: "Сушильная машина Bosch WTN86211ME" has a
brand and a catalogue code, clusters perfectly, and produces a variant the
site then renders as *"Стиральная машина Bosch WTN86211ME"*. A tumble dryer
labelled a washing machine is not a coverage gap, it is a wrong page.

`sweep()` therefore applies a denylist (`is_wanted`), earned by reading all
769 live titles across the seven leaves. It refuses 76 (9.9%) — every one of
them genuinely not the category's product, and nothing real:

| Leaf | Refused | What they are |
|---|---:|---|
| washers | 50 | drying racks, tumble dryers, stacking kits, laundry gel |
| televisions | 13 | wall-mounting services, mobile brackets |
| laptops | 11 | Windows / Bitdefender / ESET licence keys |
| acs | 2 | installation services |
| smartphones, fridges, ovens | 0 | — |

A **denylist**, not an allowlist, for the reason
[not_a_phone.py](../../narxnoma-crawler/narxnoma/sources/not_a_phone.py)
gives: asaxiy's titles are template-generated and noun-led today
("Смартфон Xiaomi …", 233 of 233), and an allowlist would silently drop a
whole category the day that template changes. The count is logged per sweep,
so a template change shows up as a moving number rather than as silence.

One entry is anchored to the start of the title on purpose:
**"Сушильная машина"** leading is a tumble dryer, but
"Стирально-сушильная машина" and "Встраиваемая стирально-сушильная машина"
are washer-dryer combos — washing machines, which olcha and uzum already list
under `washers`.

The `PRICE_MIN` fence turns out to be a second, independent line of defence
against the same noise: laundry gel at 99,000 and anti-vibration feet at
59,000 SUM are dropped before the denylist ever sees them.

## 7. Measured result

693 offers kept from a 34-request sweep, **96.8% of them attached** to a
canonical product — the highest attachment rate of the eight sources.

| Category | Offers | Attached |
|---|---:|---:|
| smartphones | 233 | 93.6% |
| acs | 118 | 98.3% |
| fridges | 107 | 100% |
| washers | 94 | 100% |
| laptops | 79 | 96.2% |
| televisions | 44 | 95.5% |
| ovens | 18 | 100% |

329 of those products are carried by at least one other store, so they became
real price comparisons rather than new single-store pages.
