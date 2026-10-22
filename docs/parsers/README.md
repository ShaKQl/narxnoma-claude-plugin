# Price-source API reference

Rebuild-grade notes for every site this project fetches from. Each file documents
the **exact request**, the **response JSON shape**, **which field is the price and in
what unit**, how to build a **valid product URL**, and the **traps that silently
produce wrong numbers**.

Everything here was derived from live traffic (browser Network tab) and then
verified by running the parser end to end and opening the resulting links.

> **Verified 2026-07-26.** Each retailer client was re-implemented from scratch using
> only what these files state, and every documented endpoint, field name, unit and URL
> pattern was asserted live — **48/48 checks passed**. That pass also corrected two
> real errors in the uzum notes (see §1 and §2 there): `Origin` is *not* the required
> header for minting a token — `Accept-Language` and `Referer` are — and the GraphQL
> endpoint needs `apollographql-client-name` + `x-iid`, without which it returns
> **HTTP 200 with an `errors` key rather than an HTTP error**.
>
> (The two internal systems were checked in that pass too; they are out of scope here —
> see the aggregator note above.)

> **Second pass, 2026-07-26 — matching quality.** The first pass verified *transport*:
> endpoints, fields, units, URLs. It could not catch matcher defects, because those
> return plausible numbers. Benchmarking all seven clients against 20 externally-sourced
> targets found three more errors, now fixed in place:
>
> 1. **[_matching-engine.md](_matching-engine.md)** — a bare `"16 256"` was read as
>    RAM = 16, which deleted the model number from `model_tokens` and made
>    **iPhone 16, 17 and Air mutually interchangeable** (measured: a 12,000,000
>    iPhone 16 matched an iPhone Air target, 1.44 M low). `air`/`fe`/`se` were also
>    missing from `MODEL_MODIFIERS`.
> 2. **[uzum.md §8](uzum.md#8-colours-are-russian--and-in-cardmodel-strings-uzbek)** —
>    "colours are Russian only" is false for card/model strings, which are often Uzbek.
>    Adding `Kumush`/`Tilla`/`Yashil`/`Muz` took uzum from **5/20 to 15/20**.
> 3. **[alifshop.md §4](alifshop.md#4-query-building--two-shot-colour-stripped-first)** —
>    "broad stripping isn't needed" is false; a `Glacier Blue` query never reaches the
>    `Синий` listing. Now two-shot.
>
> Lesson worth generalising: **a transport check cannot validate a matcher.** Wrong
> matches look exactly like right ones until you diff against an independent source.

## Files

| File | Site | Kind | Auth | Coverage* |
|---|---|---|---|---|
| [uzum.md](uzum.md) | uzum.uz | GraphQL, multi-seller | anonymous token (self-minting) | 61/66 |
| [alifshop.md](alifshop.md) | alifshop.uz | REST POST, multi-seller | none | 63/66 |
| [beemarket.md](beemarket.md) | market.beeline.uz | REST GET, single card | none | 57/66 |
| [idea.md](idea.md) | idea.uz | REST GET, single card | none | 54/66 |
| [olcha.md](olcha.md) | olcha.uz | REST GET, full catalogue | none | 52/66 |
| [texnomart.md](texnomart.md) | texnomart.uz | REST GET, single card | none | 50/66 |
| [mediapark.md](mediapark.md) | mediapark.uz | REST GET, autocomplete | none | 46/66 |
| [asaxiy.md](asaxiy.md) | asaxiy.uz | **server-rendered HTML** | none | — † |
| [radius.md](radius.md) | radius.uz | Saleor GraphQL, single card | none | — † |
| [glotr.md](glotr.md) | glotr.uz | **server-rendered HTML**, classifieds board | none (by grant — see the file) | — † |
| [openshop.md](openshop.md) | openshop.uz | REST POST, full catalogue (~120 requests) | none | — ‡ |
| [_matching-engine.md](_matching-engine.md) | — | shared name→product matcher | — | — |

> **Narxnoma is an aggregator.** The two internal systems documented in the original
> notes — `ecom.ishonchsavdo.uz` (our storefront) and `ishonchsale.uz` (our warehouse) —
> are deliberately **excluded** from this repo. We never list our own inventory beside
> competitors' prices. Their notes remain in the source `parsers/` directory.

\* phones matched out of 66 active smartphones, as of 2026-07-24.

† asaxiy (2026-08-10), radius and glotr (2026-08-11) were added after that
survey, so they have no 66-phone score. Measured on their own terms: asaxiy 693
offers at 96.8% attached; radius 274 offers at 98.9%; glotr 8,138 offers.

‡ openshop (2026-10-14) came after all three. Measured on its own terms on
2026-10-22: 769 offers across the seven categories, 5,723 products in the whole
catalogue, every one in stock.

> **Fourth pass, 2026-10-14 — a whole assortment against one new store.**
> openshop was first used to price a retailer's *entire* warehouse list (2,619
> names across 118 product types, most of them not phones) against one catalogue,
> and every matched name was then read by hand. Every automated check passed while
> the names were wrong, and every defect was in the **caller's** use of the matcher
> on names it had never been measured on. None is fixed in `matching/` yet — its
> golden corpus pins the phone behaviour — so callers outside phones must handle
> them; the repros are in [openshop.md §8](openshop.md#8-matcher-gaps-its-names-exposed):
>
> 1. `"(SIM + eSIM)"` written **with spaces** became a phantom `plus` model token,
>    so **every iPhone** was rejected (0 matched; 16 once worked around).
> 2. The non-phone path drops one-character tokens, model digits included:
>    **Galaxy Watch 4 matched Watch 8, Buds 2 Pro matched Buds 4 Pro.**
> 3. `head_for_model` cuts an appliance name at `/`, so **PRM-20MW/LA1, /LA3 and
>    /LA4 all matched /LA2** at one price.
>
> Lesson, alongside the earlier passes': **the matcher is only as tested as the
> names it has seen.** A new store's naming style is a new test corpus; read the
> pairs before trusting the counts.

> **Third pass, 2026-08-11 — what is on the row, not how many rows.** The first
> pass verified transport and the second verified matching. Neither could see a
> field that is *populated, well-formed, and wrong*, because every count stays
> identical. Three defects of exactly that shape, all now fixed:
>
> 1. **[glotr.md §3](glotr.md#3-trap--the-photos-come-before-the-name)** — the
>    photos sit *before* the name inside a card, so cutting cards at the name
>    anchor gave every listing its neighbour's picture. **55 of 55 wrong** on
>    the page it was measured on; row counts, attachment and the coverage
>    report were all unchanged by it.
> 2. **[glotr.md §4](glotr.md#4-trap--past-its-last-page-glotr-serves-other-peoples-goods)** —
>    past its last page glotr serves 21 *unrelated* products per page,
>    endlessly and never repeating, so the no-new-ids stop never fired. A
>    category holding 240 ovens ingested 2,739.
> 3. **[uzum.md](uzum.md)** — `photos` was never requested, so the largest
>    source in the catalogue published **5,461 offers with no picture at all**.
>
> Lesson worth generalising, alongside the second pass's: **aggregate metrics
> cannot see a substitution.** Count, freshness and attachment answer "is there
> a value here?", never "is it this product's value?". Checking that needs a
> second, independently-rendered copy of the same fact — the `-p-<id>` in the
> photo anchor, the `alt` text, the site's own pager — and a rule that drops
> the row when the two disagree.

> **A small source is not a weak source.** radius contributes 2.2% of the
> catalogue's offers and 4.8% of its *comparisons* — 212 of its products are
> carried by someone else, and 54 of those had only one price before it
> arrived. Judge a candidate source by the second prices it creates, not by
> its row count. See [radius.md §8](radius.md#8-measured-result).

## The one thing to understand first

Almost none of these sites can be scraped from HTML — nearly every one is a
JavaScript SPA that renders an empty shell. A headless-browser attempt across five
of them succeeded on exactly one. **The durable path is usually the private JSON API
the SPA itself calls.**

To find it for a new site: open the site, DevTools → Network → Fetch/XHR, type a
search, and look for the request whose response contains prices. Copy it as cURL.

**Check for the exception before assuming the rule.** asaxiy.uz has no catalogue
JSON endpoint at all — its only `/ajax/*` routes are login and filter plumbing —
and it server-renders a complete, fully-priced product grid into the initial HTML
document. Looking for an API there finds nothing and concludes, wrongly, that the
site cannot be crawled. See [asaxiy.md](asaxiy.md), including why the identity is
still read from machine-generated `data-` attributes rather than from prose, and
why the lighter XHR fragment is the wrong thing to fetch.

## Two shapes of retailer

This distinction decides how you turn results into one number:

- **Single-card** (beemarket, texnomart, idea, mediapark, olcha, openshop) — the retailer is
  the only seller, so one variant appears once. Take the best exact match's price.
- **Multi-seller** (uzum, alifshop) — many partners list the same variant at
  different prices. Collect all matches, strip outliers with IQR fences, take the
  **median**. uzum additionally reports a **min**.

```python
import statistics

def robust_median(prices):
    """Median after IQR outlier stripping (only strips when >= 4 samples)."""
    prices = sorted(prices)
    if not prices:
        return None, []
    if len(prices) < 4:
        return statistics.median(prices), prices
    q1, _, q3 = statistics.quantiles(prices, n=4, method="inclusive")
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    kept = [p for p in prices if lo <= p <= hi] or prices
    return statistics.median(kept), kept
```

## Rules that apply to every source

1. **Never trust a slug you built yourself.** Two sites punished this. alifshop
   products live at `/moderated-offer/<slug>`, not `/product/<slug>` (404).
   mediapark's slug is actively wrong — a 256 GB Silver phone carries a slug reading
   `...8-128-gb...`. Always open one built URL in a real browser before trusting the
   column.
2. **Verify the price against the rendered page**, not just against the JSON. This
   is how the uzum card-vs-SKU bug was caught.
3. **Clear the cell on a miss.** If a filler ever writes only on success, a later
   stricter run leaves stale values from an earlier looser pass behind. This
   produced a real data-integrity bug (idea column showed 60 filled when only 54
   matched). Every filler now writes `None` to both the price and link cell when
   there is no match.
4. **Search relevance is not precision.** Every endpoint here will happily return a
   phone case, a vacuum cleaner, or a different storage tier. The matcher — not the
   search engine — decides what counts. See [_matching-engine.md](_matching-engine.md).
5. **Broad query, strict match.** Several of these engines use strict AND semantics,
   so extra words (colour, `5G`, brand prefix) silently return zero results. Strip
   them from the *query* and enforce them in the *matcher* instead.
6. Be polite: sequential requests, ~0.3–0.6 s delay, a real `User-Agent`, and the
   `Origin`/`Referer` the site's own SPA sends.

## Output contract used by the fillers

All fillers edit `exports/<date>_phone_prices_survey.xlsx` in place and touch only
their own columns:

- Sheet **`Prices`** — integer SUM, `number_format = "#,##0"`
- Sheet **`Links`** — plain-text URL, `hyperlink = None`, `number_format = "@"`
  (kept unlinked deliberately so the cells stay copy-pasteable)

Each run also writes a full audit trail to `database/<site>_price_fill_log.json`
containing every candidate considered, its score, and the matched name — which is
what makes "why did this row get this price?" answerable after the fact.
