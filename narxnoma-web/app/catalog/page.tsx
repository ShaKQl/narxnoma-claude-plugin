import { cookies } from "next/headers";
import CategoryGrid from "@/components/CategoryGrid";
import { langFromCookie, t } from "@/lib/i18n";
import { getBrandsByCategory } from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function CatalogPage() {
  const lang = langFromCookie((await cookies()).get("lang")?.value);
  const brandRows = await getBrandsByCategory();

  // Aggregate per-category brand rows into category tiles.
  const catMap = new Map<string, { count: number; stores: number; min_price: number | null }>();
  for (const b of brandRows) {
    const cur = catMap.get(b.category) ?? { count: 0, stores: 0, min_price: null };
    // count(*) is a bigint string from pg -- sum numerically, not concat.
    cur.count += Number(b.count);
    cur.stores = Math.max(cur.stores, Number(b.stores));
    const p = b.min_price != null ? Number(b.min_price) : null;
    cur.min_price =
      cur.min_price == null || (p != null && p < cur.min_price) ? p : cur.min_price;
    catMap.set(b.category, cur);
  }
  const categoryRows = [...catMap.entries()].map(([category, v]) => ({
    category,
    count: v.count,
    stores: v.stores,
    min_price: v.min_price,
  }));

  return (
    <main>
      <div className="page">
        <section className="sec">
          <h1>{t(lang, "catalog.title")}</h1>
          <p className="sub">{t(lang, "catalog.sub")}</p>
          <CategoryGrid rows={categoryRows} columns={2} />
        </section>
      </div>
    </main>
  );
}