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
| [_matching-engine.md](_matching-engine.md) | — | shared name→product matcher | — | — |

> **Narxnoma is an aggregator.** The two internal systems documented in the original
> notes — `ecom.ishonchsavdo.uz` (our storefront) and `ishonchsale.uz` (our warehouse) —
> are deliberately **excluded** from this repo. We never list our own inventory beside
> competitors' prices. Their notes remain in the source `parsers/` directory.

\* phones matched out of 66 active smartphones, as of 2026-07-24.

† asaxiy (2026-08-10) and radius (2026-08-11) were added after that survey, so
they have no 66-phone score. Measured on their own terms: asaxiy 693 offers at
96.8% attached; radius 274 offers at 98.9%.

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

- **Single-card** (beemarket, texnomart, idea, mediapark, olcha) — the retailer is
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
