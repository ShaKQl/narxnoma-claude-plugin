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

const NON_PHONE = new Set(["televisions", "laptops", "acs", "fridges", "washers", "ovens"]);

export default async function HomePage() {
  const lang = langFromCookie((await cookies()).get("lang")?.value);
  const [stats, perCategory, brandRows] = await Promise.all([
    getHomeStats(),
    getFeaturedPerCategory(8),
    getBrandsByCategory(),
  ]);

  // Aggregate per-category brand rows into the category grid's numbers.
  const catMap = new Map<string, { count: number; stores: number; min_price: number | null }>();
  for (const b of brandRows) {
    const cur = catMap.get(b.category) ?? { count: 0, stores: 0, min_price: null };
    cur.count += Number(b.count);
    cur.stores = Math.max(cur.stores, Number(b.stores));
    const p0 = b.min_price != null ? Number(b.min_price) : null;
    cur.min_price = cur.min_price == null || (p0 != null && p0 < cur.min_price) ? p0 : cur.min_price;
    catMap.set(b.category, cur);
  }
  const categoryRows = [...catMap.entries()].map(([category, v]) => ({
    category, count: v.count, stores: v.stores, min_price: v.min_price,
  }));

  const catLabel = (c: string) => {
    const v = t(lang, `cat.${c}`);
    return v && !v.startsWith("cat.") ? v : c;
  };

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
            <Link href="/catalog" className="more-link">{t(lang, "home.more")} →</Link>
          </div>
          <CategoryGrid rows={categoryRows} columns={4} />
        </div>
      </section>

      <section className="sec">
        <div className="page">
          <div className="result-head">
            <h2>{t(lang, "home.popular")}</h2>
          </div>
          {perCategory.map(({ category, hits }) => {
            const seeAll = {
              ru: "Смотреть все →",
              uz: "Barchasini ko'rish →",
            }[lang];
            return (
              <div key={category} style={{ marginTop: 8 }}>
                <div className="row-head">
                  <h3 style={{ fontSize: 15, fontWeight: 600 }}>{catLabel(category)}</h3>
                </div>
                {NON_PHONE.has(category) ? (
                  <>
                    {/* Horizontal scroll so the user can surf the category on the
                        page, with the "see all" button under the scroller. */}
                    <div className="hscroll">
                      {hits.map((v) => <VariantCard key={v.id} v={v} />)}
                    </div>
                    <div className="hscroll-more">
                      <Link href={`/catalog?category=${category}`} className="btn">
                        {seeAll}
                      </Link>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="grid">
                      {hits.map((v) => <VariantCard key={v.id} v={v} />)}
                    </div>
                    <div className="hscroll-more">
                      <Link href={`/catalog?category=${category}`} className="btn">
                        {seeAll}
                      </Link>
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </section>
    </main>
  );
}