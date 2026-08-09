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
  storage_gb: number;
  color: string;
  sim_kind: string;
  category: string;
  min_price: number | null;
  median_price: number | null;
  max_price: number | null;
  offer_count: number;
  in_stock_offer_count: number;
  store_count: number;
  computed_at: string;
  latest_offer_at: string | null;
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
    ramCounts: Map<string, number>;
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
  "смартфон": "",
  smartfon: "",
  телефон: "",
};

export function normalizeQuery(raw: string): string {
  let q = raw.toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, " ").trim();
  q = q.replace(/\s+/g, " ");
  if (!q) return "";
  // Whole-word synonym rewrite (also expands "реди" -> "redmi"); noise words
  // map to "" and are dropped.
  const words = q.split(" ");
  const mapped = words
    .map((w) => (w in BRAND_SYNONYMS ? BRAND_SYNONYMS[w] : w))
    .filter(Boolean);
  return mapped.join(" ");
}

// ---------------------------------------------------------------------------
// Base WHERE builder shared by results + facet queries.
// "excludeFacet" lets each facet's counts ignore its own selection, so the
// sidebar shows what is *available*, not what is already checked.
// ---------------------------------------------------------------------------

interface SearchParams {
  qNorm: string;
  brands: string[];
  colors: string[];
  rams: number[];
  priceLo: number | null;
  priceHi: number | null;
  multiStore: boolean;
}

function baseWhere(p: SearchParams, excludeFacet?: "brands" | "colors" | "rams") {
  const clauses: string[] = [];
  const params: unknown[] = [];
  let i = 1;
  if (p.qNorm) {
    clauses.push(`lower(v.display_name) LIKE '%' || $${i} || '%'`);
    params.push(p.qNorm);
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
  return { where: clauses.length ? `WHERE ${clauses.join(" AND ")}` : "", params };
}

const PAGE_SIZE = 24;

export async function searchVariants(
  raw: SearchParams & { sort: SortKey; page: number }
): Promise<SearchResult> {
  const p: SearchParams = {
    qNorm: raw.qNorm,
    brands: raw.brands,
    colors: raw.colors,
    rams: raw.rams,
    priceLo: raw.priceLo,
    priceHi: raw.priceHi,
    multiStore: raw.multiStore,
  };
  const { where, params } = baseWhere(p);
  // The SELECT's brand-rank/pos expressions need the query itself as a
  // parameter. It must go in a COPY: `params` is reused by the count and
  // facet queries, which do not declare it.
  const qIdx = params.length + 1;
  const resParams = [...params, p.qNorm];

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
            CASE WHEN lower(v.brand) = $${qIdx} THEN 0
                 WHEN lower(v.brand) LIKE $${qIdx} || '%' THEN 1 ELSE 2 END AS brand_rank,
            strpos(lower(v.display_name), $${qIdx}) AS pos
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
      colors,
      rams: rams.map((r) => r.value),
      ramCounts: new Map(rams.map((r) => [String(r.value), Number(r.count)])),
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
  storage_gb: number;
  color: string;
  sim_kind: string;
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
            (SELECT s.name FROM store s WHERE s.id = vp.min_store_id) AS min_store_name
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
  return query(
    `SELECT v.category, v.brand, count(*) AS count,
            min(vp.min_price) AS min_price, max(vp.store_count) AS stores
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
            0 AS brand_rank, 0 AS pos
       FROM variant v JOIN variant_price vp ON vp.variant_id = v.id
      WHERE vp.store_count >= 2 AND vp.min_price IS NOT NULL
      ORDER BY vp.store_count DESC, vp.min_price ASC
      LIMIT 10`
  );
}

export async function getSearchSuggestions(q: string) {
  const qNorm = normalizeQuery(q);
  if (!qNorm) return { variants: [], brands: [] };
  const variants = await query(
    `SELECT v.slug, v.display_name, vp.min_price, vp.store_count
       FROM variant v JOIN variant_price vp ON vp.variant_id = v.id
      WHERE lower(v.display_name) LIKE '%' || $1 || '%'
      ORDER BY vp.store_count DESC, vp.min_price ASC NULLS LAST LIMIT 6`,
    [qNorm]
  );
  const brands = await query<{ brand: string }>(
    `SELECT DISTINCT brand FROM variant WHERE lower(brand) LIKE $1 || '%' ORDER BY brand LIMIT 5`,
    [qNorm]
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