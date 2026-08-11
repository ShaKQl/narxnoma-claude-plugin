# glotr.uz — server-rendered Yii catalogue (classifieds board)

> **Access.** glotr's `robots.txt` disallows the browse surface (`/search`,
> `/*?catid=`, `/*?page=`, `Crawl-delay: 10`) to every user agent, and names
> `ClaudeBot`/`GPTBot`/`CCBot` with `Disallow: /`. **We sweep it under an
> explicit grant from glotr.** That permission is specific to this operator and
> is what makes this client legitimate; the file itself cannot be changed on
> their side for unrelated security reasons. Do not copy this approach to
> another site whose robots.txt says the same thing.

Like [asaxiy](asaxiy.md), glotr has no JSON API. Pages are rendered server-side
(Yii: `yii.js`, `yii.activeForm.js`, `/assets/…`) and a category page carries a
complete, fully-priced product grid in the initial HTML document.

Unlike every other source here, **glotr is a classifieds board, not a shop.**
Sellers post their own listings into a category of their choosing. That single
fact drives most of what follows.

---

## 1. Request

```
GET https://glotr.uz/<category-path>/            # page 1
GET https://glotr.uz/<category-path>/?page=N     # page N
Accept-Language: ru-RU,ru;q=0.9
```

UTF-8, declared in both the `Content-Type` header and a `<meta charset>`. No
auth, no cookies, no token.

| our category | path | pages (2026-08-11) |
|---|---|---|
| smartphones | `telefoni-i-plansheti` | 38 |
| televisions | `televizori` | 20 |
| laptops | `noutbuki` | 36 |
| acs | `konditsioneri` | 58 |
| fridges | `xolodilniki` | 33 |
| washers | `stiralnie-mashini` | 23 |
| ovens | `duxovie-shkafi` | 5 |

56 cards per page, except the last.

---

## 2. The card, in source order

```html
<div class='product-card '>
  <div class='product-card__header'>
    <a href="/vstraivaemiy-…-p-881208/" class='product-card__swiper swiper-container'>
      <div class='swiper-slide'>
        <img class='lazyload-img'
             src="data:image/png;base64,…"                 <!-- 1x1 placeholder -->
             data-src='https://files.glotr.uz/company/…/….webp?_=ozauc'
             alt='Встраиваемый духовой шкаф Artel Art-Classico I6701 Серебристый'>
      …one more .swiper-slide per extra photo…
  <div class='product-card__content'>
    <a href='/vstraivaemiy-…-p-881208/' class='product-card__link …'>Встраиваемый …</a>
    <span class='text-stock text-success'>В наличии</span>
    <div class="price-retail proposal-price"> 2 610 800 <span>сум</span></div>
```

| field | where |
|---|---|
| product id | the `-p-<id>` tail of **either** anchor's href |
| name | the `product-card__link` anchor's text |
| price | `price-retail` block; space thousands separators + the word `сум` |
| availability | the `text-stock` modifier class |
| image | the **first** `.lazyload-img`'s `data-src` (`src` is a 1×1 placeholder) |

---

## 3. TRAP — the photos come before the name

**This is the one that cost us every picture on the site.**

The obvious card boundary is the `product-card__link` anchor, because it is the
only element carrying both the name and the id. Cutting cards there gives each
listing a region that *starts after its own photos and ends inside the next
card's*, so `image_url` is the neighbour's picture. Measured on page 1 of
`/duxovie-shkafi/`: **55 of 55 wrong**, shifted by exactly one card.

Nothing downstream can see it. The URL is well-formed, on the right CDN,
present on every row, and distinct per row. Row counts, attachment rates and
the coverage report are all identical whether the pictures are right or wrong.

**Cut at `<div class='product-card '` instead** — it encloses both halves — and
then read the id **twice**, from the photo anchor and from the name anchor, and
require the two to agree. A card whose ids disagree is dropped, not published:
a markup shift must cost a listing, never mint one pairing a real name with
another product's photograph.

Independent confirmation is available and cheap: each `<img>` carries an `alt`
equal to the product name (glotr blanks `"` and `,` in it). Comparing the two is
evidence that position agreeing with position is not.

---

## 4. TRAP — past its last page, glotr serves other people's goods

`?page=N` beyond the end does **not** return an empty grid, a 404, or a
redirect. It returns **21 unrelated products** under the category's own
heading (`<h1>Духовые шкафы - Страница №6</h1>`) — fridges, water coolers,
sewing machines, a face-recognition controller, an industrial chemical — and a
**different set on every page**, indefinitely.

So "stop when a page adds no product id already seen" never fires. The first
version of this client walked filler until `MAX_PAGES` and filed all of it
under whichever category it had been asked for:

| category | real size | first sweep ingested |
|---|---|---|
| ovens | 240 | **2,739** |
| smartphones | ~2,100 | 2,264 |
| acs | ~3,200 | 2,759 |

**The end signal is glotr's own pager:**

```html
<ul class="pagination-list">
  …
  <li class="next"><a href="/duxovie-shkafi/?page=5" data-page="4">&raquo;</a></li>   <!-- more -->
  <li class="next disabled"><span>&raquo;</span></li>                                 <!-- last page -->
</ul>
<!-- past the end: no <ul class="pagination-list"> at all -->
```

Follow the `next` link's `?page=` and stop when there is not one. Note the
class on the last page is `next disabled`, so matching bare `next` is not
enough — it has to be the one carrying an `<a>`.

The pager is also **windowed**: page 1 shows links to pages 2–5 only. Reading
"5 pages" off it is how this source was first sized at ~1,900 products when it
actually holds ~8,100.

Keep the no-new-ids rule underneath as a backstop, so a change in the pager
markup costs one wasted page rather than a catalogue of someone else's goods.

---

## 5. Availability — glotr's whole vocabulary

Counted live across six category pages:

| badge | text | maps to |
|---|---|---|
| `text-success` | В наличии | `IN_STOCK` |
| `text-warning` | Под заказ | `UNKNOWN` |
| `text-secondary` | Уточнить наличие | `UNKNOWN` |
| *(absent)* | — | `UNKNOWN` |

There is no fourth badge, and **no `text-danger`** — an earlier test asserted
one against a hand-written fixture that invented it.

**Nothing maps to `OUT_OF_STOCK`, and that is the finding rather than an
omission.** A seller who runs out delists rather than marking the card. "Под
заказ" means made to order and "Уточнить наличие" means ask; neither asserts
the item is gone. Reading them as `OUT_OF_STOCK` hid those offers from the
product page entirely, on the strength of a claim glotr never made. `UNKNOWN`
keeps the offer visible while still barring it from setting a headline price,
which only `IN_STOCK` may do.

---

## 6. Category filters — positive keeps, never denylists

A category page holds whatever sellers filed there. On the laptop page: a
perfume, a table, a microscope, a wireless mouse. On the oven page: furniture
repair services. This is not noise around the edges — it is the shape of the
source.

**Every category is judged by a positive keep plus an accessory drop.** A
denylist enumerates what to reject, and on a classifieds board the things to
reject are not enumerable.

Phones were the last category still on the shared `is_phone_listing` denylist,
on the reasoning that the page mixes in tablets and the phone detector already
drops those. Across all 442 names glotr serves under `/telefoni-i-plansheti/`,
that denylist kept **245**, among them:

> a SanDisk microSD card · an HP stylus · a thermal-imaging monocular · a Testo
> pyrometer · an Epson MFP · a GNSS receiver · prayer-bead rings · a pocket hand
> warmer · a patch panel · a kidney supplement · a toy kitchen · bicycle racks ·
> made-to-order shower cabins

The replacement keeps **124** of the same 442, in two measured parts:

1. **the noun rule** — the name announces a handset (`смартфон`, `iphone`,
   `мобильный телефон`, `айфон`) — keeps 120; the 4 it then loses to the
   accessory drop are a 20 W charger, a Borofone holder, a MagSafe station and
   a power bank, all of which name a phone without being one;
2. **the brand-first rule** — a leading phone brand *and* a memory pair
   (`8/256`, `8GB+256GB`, `3+64`) — adds exactly 4 more, every one a real
   handset, and no false positive.

Tablets are named exactly like handsets here — brand, model, memory pair,
colour, no "планшет" anywhere. `Redmi Pad 2 Pro 8/256 Grey` and
`Samsung X216 8/128GB Gray (Tab A9+)` were the only two wrong rows in 828 kept
phones after the first fixed sweep, and `is_phone_listing` catches neither;
`\bpad\b|\btab\b` in the accessory drop does.

Laptops keep their own rule (`_is_laptop`): the word *ноутбук/нетбук/ультрабук/
макбук* **or** a leading laptop brand, minus a long non-laptop drop list —
glotr writes laptop names both as "Ноутбук Acer…" and as bare "ASUS ROG Strix
G16", and a startswith test alone loses 142 real machines.

---

## 7. Measured result (2026-08-11, after the fixes)

- **8,138 offers**, every one with an image, across 7 categories.
- Refused as not-the-category: 917 phones, 333 ACs, 128 laptops, 122 fridges,
  124 washers, 98 TVs, 23 ovens.
- **Zero cross-category leakage**: every kept row in acs/fridges/ovens/
  televisions/washers carries its own category noun. The laptops (142) and
  phones (55) kept without one are the brand-first residues, read individually
  and confirmed.
- 5,436 rows the broken sweep had ingested were deleted from `offer`
  (`raw_offer` left intact — it is the append-only log, and those rows are a
  true record of what was seen). 2,038 products had been taking their headline
  price from one of them.

---

## 8. Prices

Rendered as `7 579 000 <span>сум</span>`. Strip spaces, then run through
`coerce_price` — never trust the raw string. Some cards carry no price at all
("цена по запросу"); they are dropped with a warning, not defaulted.
