import Link from "next/link";
import { cookies } from "next/headers";
import CategoryGrid from "@/components/CategoryGrid";
import SearchBox from "@/components/SearchBox";
import VariantCard from "@/components/VariantCard";
import { langFromCookie, plural, price, t, timeAgo } from "@/lib/i18n";
import {
  getBrandsByCategory,
  getFeaturedPerCategory,
  getHomeStats,
} from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const lang = langFromCookie((await cookies()).get("lang")?.value);
  const [stats, perCategory, brandRows] = await Promise.all([
    getHomeStats(),
    getFeaturedPerCategory(4),
    getBrandsByCategory(),
  ]);

  // Aggregate per-category brand rows into the category grid's numbers.
  const catMap = new Map<string, { count: number; stores: number; min_price: number | null }>();
  for (const b of brandRows) {
    const cur = catMap.get(b.category) ?? { count: 0, stores: 0, min_price: null };
    cur.count += b.count;
    cur.stores = Math.max(cur.stores, b.stores);
    cur.min_price =
      cur.min_price == null || (b.min_price != null && b.min_price < cur.min_price)
        ? b.min_price
        : cur.min_price;
    catMap.set(b.category, cur);
  }
  const categoryRows = [...catMap.entries()].map(([category, v]) => ({
    category,
    count: v.count,
    stores: v.stores,
    min_price: v.min_price,
  }));

  // Group brands by category for the brand section.
  const brandGroups = new Map<string, typeof brandRows>();
  for (const b of brandRows) {
    const arr = brandGroups.get(b.category) ?? [];
    arr.push(b);
    brandGroups.set(b.category, arr);
  }

  return (
    <main>
      <section className="hero">
        <h1>{t(lang, "hero.title", { n: stats.stores })}</h1>
        <p className="sub">{t(lang, "hero.sub")}</p>
        <SearchBox big />
        <div className="stat-strip">
          <div className="stat">
            <span className="num">{stats.variants_priced}</span>
            <span className="lbl">
              {plural(lang, stats.variants_priced, "model", "модель", "модели", "моделей")}
            </span>
          </div>
          <div className="stat">
            <span className="num">{stats.stores}</span>
            <span className="lbl">
              {plural(lang, stats.stores, t(lang, "stat.stores"), "магазин", "магазина", "магазинов")}
            </span>
          </div>
          <div className="stat">
            <span className="num">{stats.last_updated ? timeAgo(lang, stats.last_updated) : "—"}</span>
            <span className="lbl">{lang === "uz" ? "narx tekshiruvi" : "проверка цен"}</span>
          </div>
        </div>
      </section>

      <section className="sec">
        <div className="page">
          <div className="result-head">
            <h2>{t(lang, "home.categories")}</h2>
            <Link href="/catalog" className="more-link">
              {t(lang, "home.more")} →
            </Link>
          </div>
          <CategoryGrid rows={categoryRows} columns={4} />
        </div>
      </section>

      <section className="sec">
        <div className="page">
          <div className="result-head">
            <h2>{t(lang, "home.popular")}</h2>
          </div>
          {perCategory.map(({ category, hits }) => (
            <div key={category} style={{ marginTop: 8 }}>
              <div className="row-head">
                <h3 style={{ fontSize: 15, fontWeight: 600 }}>
                  {t(lang, `cat.${category}`)}
                </h3>
                <Link href={`/c/${category}`} className="more-link">
                  {t(lang, "home.viewCategory")}
                </Link>
              </div>
              <div className="grid">
                {hits.map((v) => (
                  <VariantCard key={v.id} v={v} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="sec">
        <div className="page">
          <div className="result-head">
            <h2>{t(lang, "home.brands")}</h2>
          </div>
          {[...brandGroups.entries()].map(([cat, list]) => (
            <div key={cat} style={{ marginTop: 8 }}>
              <h3 style={{ fontSize: 15, fontWeight: 600, margin: "18px 0 8px" }}>
                {t(lang, `cat.${cat}`)}
              </h3>
              <div className="brand-grid">
                {list.map((b) => (
                  <Link
                    key={b.brand}
                    className="brand-tile"
                    href={`/c/${b.category}/${b.brand}`}
                  >
                    <span className="b-name">{b.brand}</span>
                    <span className="b-meta">
                      {plural(lang, b.count, "model", "модель", "модели", "моделей")}
                      {b.min_price != null && ` · ${lang === "uz" ? "dan" : "от"} ${price(lang, b.min_price)}`}
                    </span>
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}