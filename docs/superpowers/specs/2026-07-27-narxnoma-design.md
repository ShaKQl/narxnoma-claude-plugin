# Narxnoma — electronics price comparison for Uzbekistan

**Status:** approved design, ready for implementation planning
**Date:** 2026-07-27
**Scope of this spec:** V1 — smartphones, Russian, mobile-first web

---

## 1. Purpose

Build the highest-quality electronics price-comparison platform in Uzbekistan. Aggregator
only — we never sell, we send traffic to retailers.

The competitive thesis is **data quality, not catalogue size**. The incumbent
(uzprice.uz) already has scale; it does not have correctness. Every architectural
decision below exists to make one promise true:

> The price we show belongs to the exact phone you are looking at, and we can show you
> which listing it came from.

### Why this is winnable — measured, not assumed

Findings from the 2026-07-26 audit of uzprice.uz. Treated as validated; do not
re-investigate without new evidence.

| Finding | Measurement |
|---|---|
| Colour pooling | 30 of 40 sampled multi-store pages pool >1 colour; **23% of all multi-store pages** show a headline price sourced from a different colour than the page title (49/210) |
| Worst observed error | Honor X7D 6/128 silver advertised at 2,149,000 — a Desert Gold price. **+200,000 sum (9.3%)** |
| Duplicate canonicals | 26 groups / 52 products differing only by case or punctuation (`Cosmic orange` vs `Cosmic Orange`) — splits the offer pool so *both* pages are wrong |
| Unstable pagination | 735-product category returns 744 rows / 720 unique ids — 24 duplicated, 15 unreachable |
| Thin comparison | 72% of smartphones are single-store (86% smartwatches, 84% tablets, 83% laptops) |
| Source concentration | alifshop supplies **76%** of smartphone offers, 31% overall — and is itself a multi-seller marketplace, so store counts overstate depth |
| Missing sources | No **uzum** (largest marketplace in UZ) and no **beemarket** |

What they do well, and we must match: 2–4 hour refresh, normalized per-category specs,
stored price history, programmatic SEO.

### Our validation of the thesis

Independently fetching all 7 sources and matching variant-exact against 20 of their most
comparison-rich pages: **17 exact agreements, 3 within 2%, 0 differing by more than 2%**
versus their own offer data re-filtered to the correct colour. uzum+beemarket produced a
cheaper legitimate price on 3/20, best case 722,000 sum (8.2%).

Honest read: *"we are cheaper"* is weak. *"our number is attributable"* is strong.

---

## 2. V1 scope

**In:**

- Smartphones only
- Russian only (Uzbek later; keep strings in one catalogue so adding a locale is a
  routing change, not a rewrite)
- Mobile-first, per the `Narxnoma Mobile.dc.html` design
- Search, category browse with brand/price/colour/RAM facets, product page
- Uzum multi-seller spread panel (min / median / seller count / range)
- Variant picker showing a separate price per colour

**Out of V1** — present in the design canvas, implemented later:

- Price-history UI (`showOldPrice = false`)
- Store trust badge (`showTrust = false`)
- Favourites / Profile (bottom nav ships Главная + Поиск only)
- UZ/RU language toggle
- Categories beyond smartphones

**Consequence to note:** screen 01's «Реальные снижения» feed is driven by price history.
In V1 that block shows *cheapest multi-store offers* instead. We deliberately do **not**
substitute retailer-supplied "old prices" — 19 of uzprice's smartphones carry ≥50%
"discounts" sourced from `oldPrice` fields our parser docs already identify as fantasy
(`uzum.fullPrice`, `texnomart.old_price = 0`, `beemarket.price`).

`showFreshness` stays **true** — `offer.last_seen` is real data from day one.

---

## 3. Sources

Supported: **uzum, alifshop, beemarket, idea, mediapark, olcha, texnomart**.
Excluded by decision: ishonchsavdo, ishonchsale (our own systems; we are an aggregator).

`parsers/*.md` is the source of truth for each client — exact request, response shape,
price field and unit, URL construction, and the traps. Contradict it only with verified
live testing, and when you do, **update the doc in the same change**.

### Sweepability — measured 2026-07-26

This determines the architecture. Six of seven can be browsed; only mediapark cannot.

| Source | Sweepable | Evidence |
|---|---|---|
| beemarket | yes, fully | empty query → 233 pages |
| alifshop | yes, per brand | `Samsung` → 50 pages (1,000 listings) |
| uzum | yes, per brand | `Samsung` → 577 total, under the ~1000 offset cap |
| texnomart | yes, generic query | `smartfon` → 25 pages (~500) |
| olcha | yes, catalogue | 22 calls, ~440 phones |
| idea | partly | `quantity=100` honoured → 94 in one call |
| **mediapark** | **no** | autocomplete, no pagination — target-driven only |

---

## 4. Architecture

Source-driven discovery, not target-driven. The current parsers assume a curated list of
phones; production must discover products itself.

```
Source APIs
   ↓  harvest      (network — the only stage that does I/O)
Raw offers
   ↓  extract      (pure function — no I/O, fully unit-testable)
Features
   ↓  cluster      (assign canonical identity, or park as unresolved)
Canonical variants
   ↓  aggregate    (min / median / IQR / spread rollups)
variant_price
   ↓  publish      (ISR revalidate for changed variants only)
Frontend
```

Every stage is independently testable. Only `harvest` touches the network; only
`publish` touches the web tier.

### Harvest has two phases, because mediapark cannot be swept

`harvest` runs in two passes:

- **Pass A — sweep.** The six browsable sources, independent of any product list.
- **Pass B — targeted.** mediapark only, searching for variants that already exist in
  the catalogue.

Pass B deliberately reads the variant list produced by the **previous** cycle rather than
the current one. Feeding it the current cycle's clustering output would make the pipeline
cyclic (harvest → cluster → harvest → cluster) for one source's benefit. The cost is that
a genuinely new phone gets its mediapark offer one cycle late — 4 hours. That is an
acceptable trade for keeping the pipeline a straight line, and mediapark is our weakest
source anyway (46/66 coverage, no pagination).

**Chosen over two alternatives.** *Target-driven scaled up* was rejected: ~4,200 requests
per cycle for 700 phones and structurally blind to any product not already on the list.
*Seeding from uzprice's open API* was rejected on three grounds — it inherits the exact
duplicate-canonical and colour-pooling defects we differentiate against, it breaks
silently when they change schema, and building a competing commercial product on a
competitor's aggregated database is avoidable legal exposure. It is retained as a **test
fixture** (see §9), not a data source.

Measured cost of the chosen approach: **~1,100–1,900 requests, 8–13 minutes** per full
cycle — cheaper than target-driven despite far wider coverage, because sweep cost scales
with catalogue size rather than product count.

### Two deployables, one database

```
narxnoma-crawler/   Python, systemd timer, VPS in Uzbekistan
narxnoma-web/       Next.js App Router, same VPS
                    └── shared PostgreSQL
```

The parsers are verified Python and stay Python. Porting them to TypeScript for language
uniformity would mean re-deriving every trap in `parsers/*.md` — the classic source of
port drift. Hosting is a UZ VPS so the crawler egresses from a local IP (source blocking
is a real risk: ishonchsale already 403s our current IP at the Cloudflare edge) and page
latency stays low for UZ users.

---

## 5. Canonical model

**Canonical products are permanent identities. Offers are temporary observations.**
Specifications belong to canonical products; prices belong to offers. Every offer retains
its originating retailer, its raw name and its URL. Nothing is inferred that cannot later
be audited.

### The variant key

```
key = (brand, model_tokens, ram_gb, storage_gb, colour, sim_kind)
```

All six derive from `extract_features` in `parsers/_matching-engine.md`. `sim_kind` is
`dual | esim_only | unknown` — an eSIM-only iPhone is a different product at a materially
different price, not a colour variant (uzum lists them side by side, 18,099,000 vs
20,789,010 for the same nominal phone).

### Identity rules — non-negotiable

- **Colour is a hard identity field.** Unknown colour never equals any colour.
- **Model numbers are sacred.** Storage/RAM extraction must never consume a model
  identifier. See the phantom-RAM trap below.
- **Model modifiers must never disappear** during parsing (`Pro`, `Max`, `Air`, `FE`).
- **Every rejection must be explainable** — `why()` returns the specific reason.

### Never guess a missing field

Sources routinely omit RAM (beemarket) or state an unresolvable colour.

1. Build full-key clusters from listings that state everything.
2. A listing with a missing field forms a *partial* key.
3. Exactly one full cluster matches → attach.
4. More than one matches → `unresolved_offer`, with reason. **Never attach.**

A `Redmi Note 15 256GB Black` with no RAM, where both 8/256 and 12/256 exist, is
genuinely ambiguous. uzprice attaches it anyway and lets it set the headline price. We
exclude it and count it. `unresolved_offer` is a **quality metric we watch**, not a
dumping ground — a rising rate means the matcher needs work.

### Display names are generated, never copied

Canonical name is built *from the key*: `Смартфон {Brand} {Model} {ram}/{storage} ГБ, {Colour}`.
Copying a store's name is exactly how uzprice produced `Cosmic orange` and `Cosmic Orange`
as two products. Generating it makes name and slug deterministic functions of the key, so
duplicates are structurally impossible.

### Matcher corrections already back-ported (2026-07-26)

Found by benchmarking, now fixed in `parsers/*.md`:

1. **Phantom-RAM collapse** — `"iPhone 16 256 GB"` has the same shape as `"12/256 GB"`,
   so the bare-pair heuristic read 16 as RAM, moving it into `reserved_nums` and deleting
   the model number from `model_tokens`. iPhone 16, 17 and Air became mutually
   interchangeable (an iPhone 16 at 12,000,000 matched an iPhone Air target, 1.44M low).
   Fixed by testing the **raw** string for a `/` separator — `normalize()` has already
   erased it — and never inferring RAM for Apple. `air`/`fe`/`se` added to
   `MODEL_MODIFIERS`.
2. **Uzum serves Uzbek colour names** in card/model strings (`Kumush`, `Tilla`, `Yashil`,
   `Muz`), though `Цвет` values are Russian. Unresolvable colours reject, so every one was
   a silent miss. Adding the vocabulary took uzum from **5/20 to 15/20**.
3. **alifshop needs broad query stripping** — a `Glacier Blue` query never reaches the
   listing alifshop stores as `Синий`. Now two-shot: colour-stripped, then verbatim,
   deduped by slug.

Generalised lesson, recorded in `parsers/README.md`: **a transport check cannot validate a
matcher.** Wrong matches look exactly like right ones until diffed against an independent
source.

---

## 6. Schema

```
store             slug, name, website_url, trust_score, is_active
raw_offer         store_id, source_key, name_raw, price, url, availability,
                  observed_at, payload jsonb            -- append-only
offer             store_id, source_key UNIQUE, variant_id?, price, availability,
                  url, first_seen, last_seen            -- current state
variant           brand, model_tokens[], ram_gb, storage_gb, colour, sim_kind,
                  display_name, slug, category          -- permanent identity
variant_price     variant_id, min, min_store_id, median, offer_count,
                  store_count, computed_at              -- render-ready rollup
unresolved_offer  offer_id, partial_key, reason, candidate_variant_ids[]
```

`raw_offer` is append-only and is where price history comes from **free** — the crawl
needs it to know what changed, so the time series accumulates whether or not the chart
ships in V1. `variant_price` is a materialised rollup so a product page is one indexed
read, not a request-time aggregation.

Index `(brand, model_tokens, ram_gb, storage_gb, sim_kind)` — this makes the colour-sibling
lookup powering the variant picker cheap.

> **`display_name` must be injective over the key (measured 2026-08-02).** It is generated
> from the key so that duplicates are structurally impossible — but it omitted `sim_kind`
> while `slug` encoded it, so an eSIM-only phone and its dual-SIM sibling, genuinely
> different products at different prices, rendered byte-identical. 42 live pairs were
> indistinguishable, including *Смартфон Apple iPhone 17 Pro 256 ГБ, Оранжевый* twice, at
> 16,985,000 and 17,690,000. **Every field of the key must reach the name.** A generator
> that drops one reintroduces exactly the confusion it exists to prevent, so the test
> asserts the invariant directly rather than pinning this one field.
>
> `display_name` is also *stored*, and `upsert_variant` uses `ON CONFLICT DO NOTHING`, so a
> name is written once at creation and never revisited. A correction to the generator would
> otherwise apply only to products first seen afterwards — the same shape as the
> `schema.sql` header rule. `refresh_display_names` regenerates them every cycle.

> **Attachments need reconciling, not just creating (measured 2026-08-02).** Clustering
> loads only offers with `variant_id IS NULL`, so an offer attached in an earlier cycle is
> never reconsidered. That is right while `name_raw` is stable and wrong the moment a
> parser fix changes it — which is precisely when the catalogue is most likely to be wrong.
> The uzum card-range repair rewrote 217 stored names; without a reconcile step every offer
> behind them would have stayed on the variant the old, incorrect name produced, and no
> report would have said so. `detach_drifted_offers` only *detaches*: the offer is then
> re-attached, or refused, by the ordinary rules, so a fix can never invent a new outcome.

---

## 7. Web layer

Next.js App Router, SSR + ISR. Routes: `/`, `/c/[category]`, `/c/[category]/[brand]`,
`/p/[slug]`, `/search`, `/stores`, `/about`, plus `/api/revalidate` (crawler webhook) and
`/api/out/[offerId]` (302 to retailer, logs the outbound click).

SEO from day one: sitemap index, per-category and category×brand landing pages, and
`robots.txt` disallowing faceted query strings with `Clean-param` hygiene.

### Design tokens

From `Narxnoma Mobile.dc.html`, so the build cannot drift:

| Token | Value |
|---|---|
| paper / card | `#EDE6D8` / `#FAF6EC` |
| ink / muted | `#211C16` / `#6B6154`, `#8A7E6C` |
| terracotta (action) | `#B0472B` |
| savings green | `#3E6B47` |
| uzum amber | `#C4881F` |
| highlight | `#F2E7CF` |
| borders | `#DED3BF`, `#EBE1CE` |

Archivo for text; **JetBrains Mono for every number** — prices, dates, counts.
`border-radius: 0` throughout, flat, no glow. Touch targets ≥44px. 390×844 baseline.

### Every design element maps to a column

| Design element | Source |
|---|---|
| `2 723 000` headline | `variant_price.min` |
| `3 магазина · до 2 811 000` | `store_count`, max offer price |
| `«Смартфон Xiaomi Redmi Note 15 8/256 ГБ, Синий»` | `offer.name_raw`, verbatim |
| `проверено 2 ч назад · в наличии` | `offer.last_seen`, `availability` |
| `Uzum · медиана 7 продавцов · разброс 2 569 000 – 2 940 000` | uzum offers → min/median/IQR |
| Variant picker per-colour price + `−154 000` | sibling variants, `variant_price.min` delta |
| `нет в продаже` | sibling with no in-stock offers |
| `2+ магазина` (default-on filter) | `store_count >= 2` |

**Counts in the design canvas are illustrative, not literal.** The mockup reads
`744 модели · 9 магазинов` — those are uzprice's numbers, carried over from the audit.
Ours are 7 sources and a catalogue size not yet known until the first full sweep runs.
Every such figure must be rendered from the database, never hardcoded from the design.

Two design decisions carrying real product weight:

**Quoting the retailer's own product name on every offer row** is the honesty mechanism —
it lets a user verify our match themselves, and it is exactly what would expose colour
pooling if a competitor did it.

**`2+ магазина` default-on** handles the 72%-single-store reality: the catalogue leads
with pages that have something to compare, and single-store pages say
`1 магазин · сравнить нечего` rather than pretending.

---

## 8. Failure handling

- **Source isolation.** Each source harvests in its own transaction. One failure degrades
  coverage; it never aborts the cycle or corrupts other sources.
- **Staleness is visible.** `last_seen` > 24h → hidden from pages. > 7d → dropped from the
  index. Store pages show the real last successful crawl. This is the direct fix for
  uzprice's joybox — dead since 2026-04-01, still flagged `HEALTHY`.
- **No price without provenance.** An offer missing `url`, `name_raw` or `last_seen` is
  rejected at write time.
- **Ambiguity is counted, not guessed.** `unresolved_offer` rate crossing ~5% raises an
  alert.
- **Sanity fences.** Price must land in 100k–100M sum, catching the whole unit-bug class
  (alifshop's tiyin divisor, a source switching currency).
- **Documented traps become assertions.** uzum token refreshes 5 min before `exp`; a
  GraphQL `200` carrying an `errors` key is a failure, not a success.
- **Idempotent crawls.** Unique on `(store_id, source_key)`; a re-run never duplicates.

---

## 9. Testing

- **Matcher unit tests** seeded from the existing `audit_*.json` files — thousands of real
  candidate names with scores and rejection reasons, free golden data. Pins all three
  regressions: iPhone Air vs 16/17, Uzbek colours, Pro vs Pro Max.
- **Clustering tests** on fixtures, asserting the ambiguous-RAM case lands in `unresolved`
  rather than attaching.
- **Source contract tests** — one live smoke test per source per day, asserting documented
  field names and units still exist. This catches silent API changes before they become
  wrong prices.
- **uzprice as an external oracle** — their API is open; a scheduled job compares our
  variant-exact minimum against their offers re-filtered to the correct colour and alerts
  if agreement falls below the ~95% measured.
- **Price-link consistency** — every filled price has a link and vice versa, per source.

---

## 10. Crawl schedule

Full sweep every 4 hours (measured 8–13 min, ample headroom). Sequential per source,
0.3–0.6s between requests, real User-Agent and the `Origin`/`Referer` each SPA sends.
Sources staggered so we never hit two hard simultaneously.

---

## 11. Pending review — decisions requiring the owner

1. **Repository location.** Spec currently written into `DerCompact/docs/`, which also
   holds unrelated pricing spreadsheets. Recommend a dedicated `narxnoma/` repo.
2. **Domain and brand registration** for Narxnoma.
3. **VPS provider and provisioning** in Uzbekistan.
4. **Monetization.** uzprice currently sends raw outbound links with no affiliate
   parameter. Whether we pursue CPC/affiliate deals affects `/api/out/` design.
5. **Legal pages** — privacy policy and PD-processing consent are required for a UZ
   consumer site; uzprice publishes both.
6. **Robots/ToS posture** toward sources — we use documented public JSON APIs politely,
   but this deserves an explicit decision.

---

## 12. Deferred, in priority order

1. Price-history UI (data accumulates from day one)
2. Uzbek locale
3. Favourites, profile, price-drop alerts
4. Categories beyond smartphones — laptops, TVs next by value
5. asaxiy, castore, radius (uzprice indexes them; asaxiy carries 12% of their offers)
6. Model comparison screen
