import type { Metadata } from "next";
import Facets from "@/components/Facets";
import SearchBox from "@/components/SearchBox";
import VariantCard from "@/components/VariantCard";
import { pluralRu } from "@/lib/format";
import { normalizeQuery, searchVariants } from "@/lib/queries";
import type { SortKey } from "@/lib/queries";

export const revalidate = 300;

export const metadata: Metadata = { title: "Поиск" };

const SORTS: { key: SortKey; label: string }[] = [
  { key: "relevance", label: "по релевантности" },
  { key: "price_asc", label: "сначала дешевле" },
  { key: "price_desc", label: "сначала дороже" },
  { key: "stores", label: "по числу магазинов" },
];

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
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
  const rams = list("ram").map((r) => (r === "none" ? NaN : Number(r))).filter((r) => !Number.isNaN(r));
  const priceBand = get("price");
  const priceLo = priceBand ? Number(priceBand) : null;
  const priceHi = priceLo != null && !Number.isNaN(priceLo) ? priceLo + 2_499_999 : null;
  const multiStore = get("multi") === "1";
  const sort = (SORTS.some((s) => s.key === get("sort")) ? get("sort") : "relevance") as SortKey;
  const page = Math.max(1, Number(get("page")) || 1);

  const res = await searchVariants({
    qNorm,
    brands,
    colors,
    rams: rams.filter((r) => Number.isFinite(r)),
    priceLo,
    priceHi,
    multiStore,
    sort,
    page,
  });

  const qs = new URLSearchParams();
  if (rawQ) qs.set("q", rawQ);
  if (brands.length) qs.set("brand", brands.join(","));
  if (colors.length) qs.set("color", colors.join(","));
  if (rams.length) qs.set("ram", rams.join(","));
  if (priceLo != null) qs.set("price", String(priceLo));
  if (multiStore) qs.set("multi", "1");
  qs.set("sort", sort);

  const title = rawQ
    ? `«${rawQ}» — ${pluralRu(res.total, "результат", "результата", "результатов")}`
    : pluralRu(res.total, "модель", "модели", "моделей");

  return (
    <main>
      <div className="page">
        <div style={{ padding: "18px 0 4px" }}>
          <SearchBox initial={rawQ} />
        </div>
        <div className="search-layout">
          <Facets f={res.facets} applied={res.applied} q={qs.toString()} />
          <section>
            <div className="result-head">
              <h2>{title}</h2>
              <span className="count">
                {rawQ && qNorm !== rawQ.toLowerCase() && (
                  <span>искали «{rawQ}» · </span>
                )}
                обновлено из базы
              </span>
            </div>
            <div className="sort-bar">
              {SORTS.map((s) => (
                <a
                  key={s.key}
                  className={sort === s.key ? "on" : ""}
                  href={`/search?${new URLSearchParams({ ...Object.fromEntries(qs), sort: s.key }).toString()}`}
                >
                  {s.label}
                </a>
              ))}
            </div>

            {res.hits.length === 0 ? (
              <div className="empty">
                <p>По запросу «{rawQ}» ничего не найдено.</p>
                <p style={{ marginTop: 8 }}>
                  Попробуйте другое написание — например, «iPhone 17» или «Redmi
                  Note 15».
                </p>
              </div>
            ) : (
              <>
                <div className="grid">
                  {res.hits.map((v) => (
                    <VariantCard key={v.id} v={v} />
                  ))}
                </div>
                {res.pages > 1 && (
                  <div className="pager">
                    {Array.from({ length: res.pages }, (_, i) => i + 1)
                      .slice(Math.max(0, res.page - 3), Math.min(res.pages, res.page + 2))
                      .map((p) => (
                        <a
                          key={p}
                          className={p === res.page ? "cur" : ""}
                          href={`/search?${new URLSearchParams({ ...Object.fromEntries(qs), page: String(p) }).toString()}`}
                        >
                          {p}
                        </a>
                      ))}
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}