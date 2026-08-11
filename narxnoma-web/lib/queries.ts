import { query } from "./db";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface VariantHit {
  id: string;
  slug: string;
  brand: string;
  display_name: string;
  ram_gb: number | null;
  // Nullable outside smartphones by design: a television has no storage, no
  // colour identity and no SIM. The columns were relaxed to NULL when
  // categories landed; these types still claimed non-null, which is how a
  // refrigerator card came to print "eSIM".
  storage_gb: number | null;
  color: string | null;
  sim_kind: string | null;
  category: string;
  min_price: number | null;
  median_price: number | null;
  max_price: number | null;
  offer_count: number;
  in_stock_offer_count: number;
  store_count: number;
  computed_at: string;
  latest_offer_at: string | null;
  image_url: string | null;
  brand_rank: number;
  pos: number;
}

export interface FacetValue {
  value: string | number;
  count: number;
  min_price?: number | null;
}

export interface SearchResult {
  hits: VariantHit[];
  total: number;
  page: number;
  pages: number;
  facets: {
    brands: FacetValue[];
    colors: FacetValue[];
    rams: (number | null)[];
    ramCounts: Record<string, number>;
    priceBands: { lo: number; hi: number; count: number }[];
    priceMin: number | null;
    priceMax: number | null;
  };
  applied: {
    q: string | null;
    brands: string[];
    colors: string[];
    rams: number[];
    priceLo: number | null;
    priceHi: number | null;
    multiStore: boolean;
    sort: string;
  };
}

export type SortKey = "relevance" | "price_asc" | "price_desc" | "stores";

// ---------------------------------------------------------------------------
// Query normalisation: brand synonyms (UZ/RU colloquial -> catalogue brand)
// and noise words. Users type "айфон 17", "реди ноут 15", "смартфон".
// ---------------------------------------------------------------------------

// Synonym targets MUST be the words that actually appear in display_name
// ("Apple iPhone 17 Pro"), because search is a substring match over it.
// Mapping "айфон" -> "apple" silently returned 0 results for "айфон 17".
const BRAND_SYNONYMS: Record<string, string> = {
  айфон: "iphone",
  iphone: "iphone",
  редми: "redmi",
  реди: "redmi",
  рилми: "realme",
  самсунг: "samsung",
  хуавей: "huawei",
  хонор: "honor",
  виво: "vivo",
  инфеникс: "infinix",
  инфиникс: "infinix",
  оппо: "oppo",
  моторола: "motorola",
  техно: "tecno",
  тecno: "tecno",
  асус: "asus",
  гугл: "google",
  галакси: "galaxy",
  галакcи: "galaxy",
  // Category nouns. display_name is generated in Russian and ALWAYS opens
  // with one ("Телевизор 7Tech 7TV4G55QLEDKS1"), so these are the most
  // searchable words in the catalogue -- they used to be discarded as noise,
  // which is why "смартфон" matched nothing while every phone was named one.
  телефон: "смартфон",
  смартфон: "смартфон",
  smartfon: "смартфон",
  telefon: "смартфон",
  televizor: "телевизор",
  noutbuk: "ноутбук",
  laptop: "ноутбук",
  konditsioner: "кондиционер",
  muzlatgich: "холодильник",
  duxovka: "духовой",
  pechka: "духовой",
};

/**
 * The query, split into the tokens a row must ALL contain.
 *
 * Search used to match `display_name LIKE '%<the whole query>%'`, which made
 * word order and adjacency mandatory: "iphone 256" found 0 of the 186 rows
 * that hold both words, and "asus vivobook 15" found 5 of 26. Users do not
 * type catalogue names in catalogue order.
 */
export function queryTokens(raw: string): string[] {
  const q = raw
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!q) return [];
  return q
    .split(" ")
    .map((w) => (w in BRAND_SYNONYMS ? BRAND_SYNONYMS[w] : w))
    .filter(Boolean);
}

export function normalizeQuery(raw: string): string {
  return queryTokens(raw).join(" ");
}

/**
 * Case-folded display_name, explicitly under ICU.
 *
 * THE DATABASE IS LC_COLLATE=C / LC_CTYPE=C, so Postgres' own `lower()` folds
 * ASCII and leaves everything else alone: `lower('Телевизор Samsung')` is
 * `'Телевизор samsung'`. Every one of the catalogue's display names opens
 * with a Cyrillic capital, so before this every Cyrillic search in the site
 * returned exactly nothing -- "телевизор", "холодильник", "ноутбук",
 * "кондиционер", all zero, on a catalogue where those words name thousands of
 * rows. ILIKE and citext read the same ctype and are no help; pg_trgm is not
 * installed. ICU is compiled in (784 collations), and `lower(x COLLATE
 * "und-x-icu")` folds Cyrillic correctly, so the fix is per-expression and
 * needs neither an extension nor a database rebuild.
 *
 * Use this ANYWHERE a user's typed text is compared to catalogue text. A bare
 * lower() will appear to work in every English test and silently fail for the
 * language the site is actually written in.
 */
const FOLDED_NAME = `lower(v.display_name COLLATE "und-x-icu")`;
const FOLDED_BRAND = `lower(v.brand COLLATE "und-x-icu")`;

/**
 * The picture for one grid card, as `v.id`'s cheapest available image.
 *
 * Restricted to IN_STOCK offers this returned nothing for 1,936 of 11,150
 * listed products, because whether a picture exists and whether the cheapest
 * seller happens to have stock are unrelated facts. The out-of-stock tier is
 * a fallback only, so a card still shows the in-stock seller's picture
 * whenever there is one.
 */
const CARD_IMAGE = `COALESCE(
              (SELECT o.image_url FROM offer o
                WHERE o.variant_id = v.id AND o.image_url IS NOT NULL
                  AND o.availability = 'IN_STOCK'
                ORDER BY o.price LIMIT 1),
              (SELECT o.image_url FROM offer o
                WHERE o.variant_id = v.id AND o.image_url IS NOT NULL
                ORDER BY o.price LIMIT 1)
            )`;

// ---------------------------------------------------------------------------
// Base WHERE builder shared by results + facet queries.
// "excludeFacet" lets each facet's counts ignore its own selection, so the
// sidebar shows what is *available*, not what is already checked.
// ---------------------------------------------------------------------------

interface SearchParams {
  qNorm: string;
  /** Every token the row must contain; see queryTokens. */
  qTokens: string[];
  brands: string[];
  colors: string[];
  rams: number[];
  priceLo: number | null;
  priceHi: number | null;
  multiStore: boolean;
  category: string | null;
}

function baseWhere(p: SearchParams, excludeFacet?: "brands" | "colors" | "rams") {
  const clauses: string[] = [];
  const params: unknown[] = [];
  let i = 1;
  // Every token must appear, in any order, in the catalogue name OR in what
  // some retailer calls the same product.
  //
  // display_name is GENERATED from the variant key, so it carries only what
  // the matcher treats as identity -- and the matcher drops marketing words.
  // "Galaxy" is one of them: 1,730 offers say Galaxy, 9 display names do, so
  // "samsung galaxy a26" -- the ordinary way to name that phone -- matched
  // nothing while the phone sat in the catalogue as "Смартфон Samsung A26
  // 8/256 ГБ, Чёрный". Searching the offers as well costs about 100ms over
  // 8,600 variants and needs no change to identity, which is the one thing
  // that must not move to make a search box work.
  for (const token of p.qTokens) {
    clauses.push(
      `(${FOLDED_NAME} LIKE '%' || $${i} || '%'
        OR EXISTS (SELECT 1 FROM offer o
                    WHERE o.variant_id = v.id
                      AND lower(o.name_raw COLLATE "und-x-icu") LIKE '%' || $${i} || '%'))`
    );
    params.push(token);
    i += 1;
  }
  if (excludeFacet !== "brands" && p.brands.length) {
    clauses.push(`v.brand = ANY($${i}::text[])`);
    params.push(p.brands);
    i += 1;
  }
  if (excludeFacet !== "colors" && p.colors.length) {
    clauses.push(`v.color = ANY($${i}::text[])`);
    params.push(p.colors);
    i += 1;
  }
  if (excludeFacet !== "rams" && p.rams.length) {
    clauses.push(`v.ram_gb = ANY($${i}::int[])`);
    params.push(p.rams);
    i += 1;
  }
  if (p.priceLo != null) {
    clauses.push(`vp.min_price >= $${i}`);
    params.push(p.priceLo);
    i += 1;
  }
  if (p.priceHi != null) {
    clauses.push(`vp.min_price <= $${i}`);
    params.push(p.priceHi);
    i += 1;
  }
  if (p.multiStore) {
    clauses.push("vp.store_count >= 2");
  }
  if (p.category) {
    clauses.push(`v.category = $${i}`);
    params.push(p.category);
    i += 1;
  }
  return { where: clauses.length ? `WHERE ${clauses.join(" AND ")}` : "", params };
}

const PAGE_SIZE = 24;

export async function searchVariants(
  raw: SearchParams & { sort: SortKey; page: number }
): Promise<SearchResult> {
  const p: SearchParams = {
    qNorm: raw.qNorm,
    qTokens: raw.qTokens,
    brands: raw.brands,
    colors: raw.colors,
    rams: raw.rams,
    priceLo: raw.priceLo,
    priceHi: raw.priceHi,
    multiStore: raw.multiStore,
    category: raw.category,
  };
  const { where, params } = baseWhere(p);
  // The SELECT's brand-rank/pos expressions need a query term as a parameter.
  // It must go in a COPY: `params` is reused by the count and facet queries,
  // which do not declare it. The FIRST token is the ranking term -- with
  // token matching there is no single "the query" string to position, and the
  // leading word is what a user is anchoring on ("samsung a26" -> samsung).
  const qIdx = params.length + 1;
  const rankTerm = p.qTokens[0] ?? "";
  const resParams = [...params, rankTerm];

  // --- results ------------------------------------------------------------
  const orderBy = {
    relevance: `brand_rank, pos, vp.store_count DESC, vp.min_price ASC NULLS LAST`,
    price_asc: `vp.min_price ASC NULLS LAST, vp.store_count DESC`,
    price_desc: `vp.min_price DESC NULLS LAST`,
    stores: `vp.store_count DESC, vp.min_price ASC NULLS LAST`,
  }[raw.sort];

  const res = await query(
    `SELECT v.id, v.slug, v.brand, v.display_name, v.ram_gb, v.storage_gb,
            v.color, v.sim_kind, v.category,
            vp.min_price, vp.median_price, vp.max_price,
            vp.offer_count, vp.in_stock_offer_count, vp.store_count, vp.computed_at,
            (SELECT max(o.last_seen) FROM offer o WHERE o.variant_id = v.id) AS latest_offer_at,
            ${CARD_IMAGE} AS image_url,
            CASE WHEN ${FOLDED_BRAND} = $${qIdx} THEN 0
                 WHEN ${FOLDED_BRAND} LIKE $${qIdx} || '%' THEN 1 ELSE 2 END AS brand_rank,
            -- strpos returns 0 when the term is absent, which would sort
            -- those rows FIRST. Push them last instead.
            CASE WHEN strpos(${FOLDED_NAME}, $${qIdx}) = 0 THEN 2147483647
                 ELSE strpos(${FOLDED_NAME}, $${qIdx}) END AS pos
       FROM variant v
       JOIN variant_price vp ON vp.variant_id = v.id
       ${where}
      ORDER BY ${orderBy}
      LIMIT ${PAGE_SIZE} OFFSET ${(raw.page - 1) * PAGE_SIZE}`,
    resParams
  );
  const totalRes = await query<{ n: string }>(
    `SELECT count(*) AS n FROM variant v JOIN variant_price vp ON vp.variant_id = v.id ${where}`,
    params
  );
  const total = Number(totalRes[0]?.n ?? 0);

  // --- facets --------------------------------------------------------------
  const brands = await query<FacetValue>(
    `SELECT v.brand AS value, count(*) AS count, min(vp.min_price) AS min_price
       FROM variant v JOIN variant_price vp ON vp.variant_id = v.id
       ${baseWhere(p, "brands").where}
      GROUP BY v.brand ORDER BY count DESC, min_price ASC`,
    baseWhere(p, "brands").params
  );
  const colors = await query<FacetValue>(
    `SELECT v.color AS value, count(*) AS count
       FROM variant v JOIN variant_price vp ON vp.variant_id = v.id
       ${baseWhere(p, "colors").where}
      GROUP BY v.color ORDER BY count DESC`,
    baseWhere(p, "colors").params
  );
  const rams = await query<{ value: number | null; count: string }>(
    `SELECT v.ram_gb AS value, count(*) AS count
       FROM variant v JOIN variant_price vp ON vp.variant_id = v.id
       ${baseWhere(p, "rams").where}
      GROUP BY v.ram_gb ORDER BY v.ram_gb ASC NULLS FIRST`,
    baseWhere(p, "rams").params
  );
  const priceRes = await query<{ lo: number | null; hi: number | null }>(
    `SELECT min(vp.min_price) AS lo, max(vp.min_price) AS hi
       FROM variant v JOIN variant_price vp ON vp.variant_id = v.id
       ${baseWhere(p).where}`,
    baseWhere(p).params
  );
  // node-pg returns bigint as string; coerce before ANY comparison or math.
  const priceLo = priceRes[0]?.lo != null ? Number(priceRes[0].lo) : null;
  const priceHi = priceRes[0]?.hi != null ? Number(priceRes[0].hi) : null;

  // Price bands of ~2.5M SUM for the facet (fits the 1.6–34M observed range).
  // One query: width_bucket over the base set, mapped back to band edges.
  const bands: { lo: number; hi: number; count: number }[] = [];
  if (priceLo != null && priceHi != null && priceHi > priceLo) {
    const STEP = 2_500_000;
    const lo = priceLo - (priceLo % STEP);
    const hi = Math.ceil(priceHi / STEP) * STEP;
    const nb = Math.max(1, Math.ceil((hi - lo) / STEP));
    // width_bucket's parameters come AFTER the WHERE clause's, so their
    // placeholders must be offset by the where-param count.
    const bw = baseWhere(p);
    const w3 = bw.params.length + 1;
    const w4 = w3 + 1;
    const w5 = w4 + 1;
    const bandRes = await query<{ bucket: number; n: string }>(
      `SELECT width_bucket(vp.min_price, $${w3}, $${w4}, $${w5}) AS bucket, count(*) AS n
         FROM variant v JOIN variant_price vp ON vp.variant_id = v.id
         ${bw.where}
        GROUP BY bucket ORDER BY bucket`,
      [...bw.params, lo, hi + STEP, nb]
    );
    for (const r of bandRes) {
      // width_bucket yields NULL for variants whose min_price is NULL
      // (out-of-stock-only); they have no price and must not appear in a
      // price band as garbage (measured: "2 500 000сум — 1сум", 303 rows).
      if (r.bucket == null) continue;
      const bLo = lo + (Number(r.bucket) - 1) * STEP;
      bands.push({ lo: bLo, hi: bLo + STEP - 1, count: Number(r.n) });
    }
    if (bands.length > 8) bands.splice(0, bands.length - 8);
  }

  return {
    hits: res as unknown as VariantHit[],
    total,
    page: raw.page,
    pages: Math.max(1, Math.ceil(total / PAGE_SIZE)),
    facets: {
      brands,
      // Colour and RAM are PHONE facets. Outside smartphones both columns are
      // NULL by design, so an unfiltered GROUP BY yields a single null bucket
      // that renders as an empty, unclickable chip on every television and
      // fridge result page. Dropping the null bucket makes the facet list
      // category-aware without needing to know the category: a result set with
      // no colours simply offers no colour filter.
      colors: colors.filter((c) => c.value != null),
      rams: rams.map((r) => r.value).filter((v) => v != null),
      // Plain object, NOT a Map: SearchResult crosses both RSC (initial SSR)
      // and the /api/search JSON endpoint, and Maps serialize to {} in JSON,
      // which then throws on .get() client-side (the facet-click bug
      // 2026-08-10).
      ramCounts: Object.fromEntries(
        rams
          .filter((r) => r.value != null)
          .map((r) => [String(r.value), Number(r.count)])
      ),
      priceBands: bands,
      priceMin: priceLo,
      priceMax: priceHi,
    },
    applied: {
      q: raw.qNorm || null,
      brands: p.brands,
      colors: p.colors,
      rams: p.rams,
      priceLo: p.priceLo,
      priceHi: p.priceHi,
      multiStore: p.multiStore,
      sort: raw.sort,
    },
  };
}

// ---------------------------------------------------------------------------
// Product page
// ---------------------------------------------------------------------------

export interface OfferRow {
  id: string;
  name_raw: string;
  price: number;
  availability: string;
  last_seen: string;
  url: string | null;
  image_url: string | null;
  store_name: string;
  store_slug: string;
}

export interface StoreRollup {
  store_name: string;
  store_slug: string;
  offers: number;
  in_stock: number;
  min_p: number | null;
  max_p: number | null;
  median_p: number | null;
  last_seen: string | null;
}

export interface SiblingRow {
  id: string;
  slug: string;
  color: string;
  display_name: string;
  min_price: number | null;
  in_stock_offer_count: number;
  store_count: number;
}

export interface VariantRow {
  id: string;
  slug: string;
  brand: string;
  display_name: string;
  ram_gb: number | null;
  // Nullable outside smartphones by design: a television has no storage, no
  // colour identity and no SIM. The columns were relaxed to NULL when
  // categories landed; these types still claimed non-null, which is how a
  // refrigerator card came to print "eSIM".
  storage_gb: number | null;
  color: string | null;
  sim_kind: string | null;
  category: string;
}

export interface PriceRow {
  min_price: number | null;
  median_price: number | null;
  max_price: number | null;
  offer_count: number;
  in_stock_offer_count: number;
  store_count: number;
  computed_at: string;
  min_offer_id: string | null;
  min_offer_name: string | null;
  min_offer_url: string | null;
  min_store_name: string | null;
  hero_image_url: string | null;
}

export interface VariantPage {
  variant: VariantRow | null;
  price: PriceRow | null;
  offers: OfferRow[];
  stores: StoreRollup[];
  siblings: SiblingRow[];
}

export async function getVariantPage(slug: string): Promise<VariantPage> {
  const variants = await query<VariantRow>(
    `SELECT id, slug, brand, display_name, ram_gb, storage_gb, color, sim_kind, category
       FROM variant WHERE slug = $1`,
    [slug]
  );
  if (!variants.length) return { variant: null, price: null, offers: [], stores: [], siblings: [] };
  const v = variants[0];

  const price = await query<PriceRow>(
    `SELECT vp.min_price, vp.median_price, vp.max_price, vp.offer_count,
 vp.in_stock_offer_count, vp.store_count, vp.computed_at,
 vp.min_offer_id,
 (SELECT o.name_raw FROM offer o WHERE o.id = vp.min_offer_id) AS min_offer_name,
            (SELECT o.url FROM offer o WHERE o.id = vp.min_offer_id) AS min_offer_url,
            (SELECT s.name FROM store s WHERE s.id = vp.min_store_id) AS min_store_name,
            -- The hero picture used to be the CHEAPEST offer's picture and
            -- nothing else, so a variant whose cheapest seller publishes no
            -- image showed no image at all -- while the grid card for the
            -- same product, which already picked the cheapest offer that HAS
            -- one, showed it. Clicking a product made its picture disappear.
            -- uzum alone accounts for 5,461 imageless offers, and 302
            -- variants had a picture available and rendered none.
            --
            -- Preference order, cheapest first within each tier: the min
            -- offer, then any in-stock offer, then any offer at all. A
            -- picture from a second retailer of the same product is right;
            -- an empty frame is not.
            COALESCE(
              (SELECT o.image_url FROM offer o
                WHERE o.id = vp.min_offer_id AND o.image_url IS NOT NULL),
              (SELECT o.image_url FROM offer o
                WHERE o.variant_id = vp.variant_id AND o.image_url IS NOT NULL
                  AND o.availability = 'IN_STOCK'
                ORDER BY o.price LIMIT 1),
              (SELECT o.image_url FROM offer o
                WHERE o.variant_id = vp.variant_id AND o.image_url IS NOT NULL
                ORDER BY o.price LIMIT 1)
            ) AS hero_image_url
       FROM variant_price vp WHERE vp.variant_id = $1`,
    [v.id]
  );

  const offers = await query<OfferRow>(
    `SELECT o.id, o.name_raw, o.price, o.availability, o.last_seen, o.url, o.image_url,
            s.name AS store_name, s.slug AS store_slug
       FROM offer o JOIN store s ON s.id = o.store_id
      WHERE o.variant_id = $1 AND o.availability <> 'OUT_OF_STOCK'
      ORDER BY (o.availability = 'IN_STOCK') DESC, o.price ASC`,
    [v.id]
  );

  const stores = await query<StoreRollup>(
    `SELECT s.name AS store_name, s.slug AS store_slug,
            count(*) AS offers,
            count(*) FILTER (WHERE o.availability = 'IN_STOCK') AS in_stock,
            min(o.price) AS min_p, max(o.price) AS max_p,
            percentile_disc(0.5) WITHIN GROUP (ORDER BY o.price) AS median_p,
            max(o.last_seen) AS last_seen
       FROM offer o JOIN store s ON s.id = o.store_id
      WHERE o.variant_id = $1
      GROUP BY s.id, s.name, s.slug
      ORDER BY min_p ASC NULLS LAST, s.name`,
    [v.id]
  );

  // Colour siblings = same model, only colour differs. The catalogue can
  // hold SEVERAL models per (brand, storage, ram, sim) -- e.g. Samsung A26
  // vs A26 5G split into separate canonicals -- so (brand, storage, ram,
  // sim) alone over-groups and the picker would compare different phones
  // ("Черный", "Черный" ×4 with −1.4M deltas). The display_name stem
  // (everything before the colour) is the same-model identity here.
  const stem = v.display_name.split(",")[0]!.trim();
  const siblings = await query<SiblingRow>(
    `SELECT v.id, v.slug, v.color, v.display_name,
            vp.min_price, vp.in_stock_offer_count, vp.store_count
       FROM variant v JOIN variant_price vp ON vp.variant_id = v.id
      WHERE v.brand = $1 AND v.storage_gb = $2
        AND v.ram_gb IS NOT DISTINCT FROM $3 AND v.sim_kind = $4
        AND split_part(v.display_name, ',', 1) = $5
      ORDER BY vp.min_price ASC NULLS LAST`,
    [v.brand, v.storage_gb, v.ram_gb, v.sim_kind, stem]
  );

  return {
    variant: v,
    price: price[0] ?? null,
    offers,
    stores,
    siblings,
  };
}

// ---------------------------------------------------------------------------
// Browse / home
// ---------------------------------------------------------------------------

export async function getBrandsByCategory(): Promise<
  { category: string; brand: string; count: number; min_price: number | null; stores: number }[]
> {
  // ::int on both aggregates, deliberately. node-pg returns bigint as a
  // STRING, and the home page SUMS these per category to size its category
  // tiles -- so `cur.count += b.count` concatenated "12" and "5" into "125"
  // instead of adding them, and the min_price comparison compared strings.
  // Same trap the price-band code already hit; casting in SQL fixes it at the
  // source rather than at each call site. Every value here fits in int4:
  // prices are fenced at 100,000,000.
  return query(
    `SELECT v.category, v.brand, count(*)::int AS count,
            min(vp.min_price)::int AS min_price, max(vp.store_count)::int AS stores
       FROM variant v JOIN variant_price vp ON vp.variant_id = v.id
      GROUP BY v.category, v.brand
      ORDER BY v.category, count DESC`
  );
}

export async function getHomeStats(): Promise<{
  variants_priced: number;
  stores: number;
  unresolved: number;
  last_updated: string | null;
  variants_total: number;
}> {
  const r = await query<{
    variants_priced: string;
    variants_total: string;
    stores: string;
    unresolved: string;
    last_updated: string | null;
  }>(
    `SELECT (SELECT count(*) FROM variant_price WHERE min_price IS NOT NULL) AS variants_priced,
            (SELECT count(*) FROM variant) AS variants_total,
            (SELECT count(*) FROM store WHERE is_active) AS stores,
            (SELECT count(*) FROM unresolved_offer) AS unresolved,
            (SELECT max(last_seen) FROM offer) AS last_updated`
  );
  const row = r[0]!;
  return {
    variants_priced: Number(row.variants_priced),
    stores: Number(row.stores),
    unresolved: Number(row.unresolved),
    last_updated: row.last_updated,
    variants_total: Number(row.variants_total),
  };
}

export async function getFeatured(): Promise<VariantHit[]> {
  return query(
    `SELECT v.id, v.slug, v.brand, v.display_name, v.ram_gb, v.storage_gb,
            v.color, v.sim_kind, v.category,
            vp.min_price, vp.median_price, vp.max_price,
            vp.offer_count, vp.in_stock_offer_count, vp.store_count, vp.computed_at,
            (SELECT max(o.last_seen) FROM offer o WHERE o.variant_id = v.id) AS latest_offer_at,
            ${CARD_IMAGE} AS image_url,
            0 AS brand_rank, 0 AS pos
       FROM variant v JOIN variant_price vp ON vp.variant_id = v.id
      WHERE vp.store_count >= 2 AND vp.min_price IS NOT NULL
      ORDER BY vp.store_count DESC, vp.min_price ASC
      LIMIT 10`
  );
}

/** Top `per` products from EACH category (by store count, then price). Lets
 *  the home page show a slice of every category, not just phones. */
export async function getFeaturedPerCategory(
  per: number = 4
): Promise<{ category: string; hits: VariantHit[] }[]> {
  const rows = await query<{ category: string; rn: number } & VariantHit>(
    `WITH ranked AS (
        SELECT v.id, v.slug, v.brand, v.display_name, v.ram_gb, v.storage_gb,
               v.color, v.sim_kind, v.category,
               vp.min_price, vp.median_price, vp.max_price,
               vp.offer_count, vp.in_stock_offer_count, vp.store_count, vp.computed_at,
               (SELECT max(o.last_seen) FROM offer o WHERE o.variant_id = v.id) AS latest_offer_at,
               ${CARD_IMAGE} AS image_url,
               -- Carried by most retailers first, then most widely stocked,
               -- and only then cheapest. Ordering by price alone fills an
               -- appliance row with the cheapest no-name units in the
               -- catalogue, which is the opposite of a shop window.
               ROW_NUMBER() OVER (
                 PARTITION BY v.category
                 ORDER BY vp.store_count DESC,
                          vp.in_stock_offer_count DESC,
                          vp.min_price ASC
               ) AS rn
          FROM variant v JOIN variant_price vp ON vp.variant_id = v.id
         WHERE vp.min_price IS NOT NULL
    )
    SELECT * FROM ranked WHERE rn <= $1 ORDER BY category, rn`,
    [per]
  );
  const groups = new Map<string, VariantHit[]>();
  for (const r of rows) {
    // `category` stays ON the hit as well as keying the group: VariantHit
    // declares it, and a card that needs to know what it is showing (spec
    // chips, links) would otherwise read undefined.
    const { rn: _rn, ...hit } = r;
    const arr = groups.get(r.category) ?? [];
    arr.push(hit as VariantHit);
    groups.set(r.category, arr);
  }
  return [...groups.entries()].map(([category, hits]) => ({ category, hits }));
}

/** A category's products, most widely carried first.
 *
 *  The category page used to borrow getFeaturedPerCategory, which ranks every
 *  category at once and then throws away all but one — so a category holding
 *  492 televisions showed eight of them and a list of brand tiles. This asks
 *  for one category directly and asks for enough of it to look like a shop.
 */
export async function getCategoryProducts(
  category: string,
  limit: number = 24
): Promise<VariantHit[]> {
  return query<VariantHit>(
    `SELECT v.id, v.slug, v.brand, v.display_name, v.ram_gb, v.storage_gb,
            v.color, v.sim_kind, v.category,
            vp.min_price, vp.median_price, vp.max_price,
            vp.offer_count, vp.in_stock_offer_count, vp.store_count, vp.computed_at,
            (SELECT max(o.last_seen) FROM offer o WHERE o.variant_id = v.id) AS latest_offer_at,
            ${CARD_IMAGE} AS image_url,
            0 AS brand_rank, 0 AS pos
       FROM variant v JOIN variant_price vp ON vp.variant_id = v.id
      WHERE v.category = $1 AND vp.min_price IS NOT NULL
      ORDER BY vp.store_count DESC, vp.in_stock_offer_count DESC, vp.min_price ASC
      LIMIT $2`,
    [category, limit]
  );
}

/** How many priced products a category holds, for the page heading. */
export async function getCategoryCount(category: string): Promise<number> {
  const rows = await query<{ n: string }>(
    `SELECT count(*) AS n
       FROM variant v JOIN variant_price vp ON vp.variant_id = v.id
      WHERE v.category = $1 AND vp.min_price IS NOT NULL`,
    [category]
  );
  return Number(rows[0]?.n ?? 0);
}

export async function getSearchSuggestions(q: string) {
  // Same token rule and same ICU fold as the results page. When the two
  // disagree the dropdown offers products the search page then cannot find,
  // which reads as the search box being broken even when it is not.
  const tokens = queryTokens(q);
  if (!tokens.length) return { variants: [], brands: [] };
  const clauses = tokens
    .map(
      (_, n) =>
        `(${FOLDED_NAME} LIKE '%' || $${n + 1} || '%'
          OR EXISTS (SELECT 1 FROM offer o
                      WHERE o.variant_id = v.id
                        AND lower(o.name_raw COLLATE "und-x-icu") LIKE '%' || $${n + 1} || '%'))`
    )
    .join(" AND ");
  const variants = await query(
    `SELECT v.slug, v.display_name, vp.min_price, vp.store_count
       FROM variant v JOIN variant_price vp ON vp.variant_id = v.id
      WHERE ${clauses}
      ORDER BY vp.store_count DESC, vp.min_price ASC NULLS LAST LIMIT 6`,
    tokens
  );
  const brands = await query<{ brand: string }>(
    `SELECT DISTINCT v.brand FROM variant v
      WHERE ${FOLDED_BRAND} LIKE $1 || '%' ORDER BY v.brand LIMIT 5`,
    [tokens[0]]
  );
  return { variants, brands: brands.map((b) => b.brand) };
}

// ---------------------------------------------------------------------------
// Stores page
// ---------------------------------------------------------------------------

export interface StoreHealth {
  name: string;
  slug: string;
  website_url: string;
  is_active: boolean;
  offers: number;
  fresh_24h: number;
  newest_offer: string | null;
  last_ok: string | null;
  last_try: string | null;
  last_error: string | null;
}

export async function getStoresHealth(): Promise<StoreHealth[]> {
  return query(
    `SELECT s.name, s.slug, s.website_url, s.is_active,
            (SELECT count(*) FROM offer o WHERE o.store_id = s.id) AS offers,
            (SELECT count(*) FROM offer o WHERE o.store_id = s.id
               AND o.last_seen > now() - interval '24 hours') AS fresh_24h,
            (SELECT max(o.last_seen) FROM offer o WHERE o.store_id = s.id) AS newest_offer,
            (SELECT max(h.finished_at) FROM harvest_run h
               WHERE h.store_id = s.id AND h.ok) AS last_ok,
            (SELECT max(h.started_at) FROM harvest_run h WHERE h.store_id = s.id) AS last_try,
            (SELECT h.error FROM harvest_run h
               WHERE h.store_id = s.id AND NOT h.ok
               ORDER BY h.started_at DESC LIMIT 1) AS last_error
       FROM store s ORDER BY s.name`
  );
}

// ---------------------------------------------------------------------------
// Outbound click tracking (used by /api/out/[offerId])
// ---------------------------------------------------------------------------

export async function getOfferForOut(
  offerId: string
): Promise<{ url: string; variant_id: string | null; store_id: string | null } | null> {
  const r = await query<{ url: string; variant_id: string | null; store_id: string | null }>(
    `SELECT url, variant_id, store_id FROM offer WHERE id = $1`,
    [offerId]
  );
  return r[0] ?? null;
}

export async function recordOutbound(
  offerId: string,
  variantId: string | null,
  storeId: string | null,
  referer: string | null
): Promise<void> {
  await query(
    `INSERT INTO outbound_click (offer_id, variant_id, store_id, referer) VALUES ($1, $2, $3, $4)`,
    [offerId, variantId, storeId, referer]
  );
}