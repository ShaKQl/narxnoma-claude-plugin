import { normalizeQuery } from "./queries";
import type { SortKey } from "./queries";

export interface ParsedSearch {
  rawQ: string;
  qNorm: string;
  brands: string[];
  colors: string[];
  rams: number[];
  priceLo: number | null;
  priceHi: number | null;
  multiStore: boolean;
  category: string | null;
  sort: SortKey;
  page: number;
  /** URLSearchParams string carrying every applied filter (for /api/search). */
  qs: string;
}

const SORTS: SortKey[] = ["relevance", "price_asc", "price_desc", "stores"];

/**
 * Shared by the SSR search page and /api/search so a facet toggle refetches
 * EXACTLY what the server rendered for the same URL.
 */
export function parseSearchParams(
  sp: Record<string, string | string[] | undefined>
): ParsedSearch {
  const get = (k: string): string => {
    const v = sp[k];
    return Array.isArray(v) ? (v[0] ?? "") : (v ?? "");
  };
  const list = (k: string): string[] =>
    get(k)
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

  const rawQ = get("q");
  const qNorm = normalizeQuery(rawQ);
  const brands = list("brand");
  const colors = list("color");
  const rams = list("ram")
    .map((r) => (r === "none" ? NaN : Number(r)))
    .filter((r) => !Number.isNaN(r) && Number.isFinite(r));
  const priceBand = get("price");
  const priceLo = priceBand ? Number(priceBand) : null;
  const priceHi =
    priceLo != null && !Number.isNaN(priceLo) ? priceLo + 2_499_999 : null;
  const multiStore = get("multi") === "1";
  const category = get("category") || null;
  const sortRaw = get("sort") as SortKey;
  const sort: SortKey = SORTS.includes(sortRaw) ? sortRaw : "relevance";
  const page = Math.max(1, Number(get("page")) || 1);

  const qs = new URLSearchParams();
  if (rawQ) qs.set("q", rawQ);
  if (brands.length) qs.set("brand", brands.join(","));
  if (colors.length) qs.set("color", colors.join(","));
  if (rams.length) qs.set("ram", rams.join(","));
  if (priceLo != null) qs.set("price", String(priceLo));
  if (multiStore) qs.set("multi", "1");
  if (category) qs.set("category", category);
  qs.set("sort", sort);
  if (page > 1) qs.set("page", String(page));

  return {
    rawQ,
    qNorm,
    brands,
    colors,
    rams,
    priceLo,
    priceHi,
    multiStore,
    category,
    sort,
    page,
    qs: qs.toString(),
  };
}