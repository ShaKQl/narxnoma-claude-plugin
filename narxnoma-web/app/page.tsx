import Link from "next/link";
import { cookies } from "next/headers";
import SearchBox from "@/components/SearchBox";
import VariantCard from "@/components/VariantCard";
import { langFromCookie, plural, price, t, timeAgo } from "@/lib/i18n";
import { getBrandsByCategory, getFeatured, getHomeStats } from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const lang = langFromCookie((await cookies()).get("lang")?.value);
  const [stats, featured, brands] = await Promise.all([
    getHomeStats(),
    getFeatured(),
    getBrandsByCategory(),
  ]);

  return (
    <main>
      <section className="hero">
        <h1>{t(lang, "hero.title", { n: stats.stores })}</h1>
        <p className="sub">{t(lang, "hero.sub")}</p>
        <SearchBox big />
        <div className="stat-strip">
          <div className="stat">
            <span className="num">{stats.variants_priced}</span>
            <span className="lbl">{plural(lang, stats.variants_priced, "model", "модель", "модели", "моделей")}</span>
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

      <section className="sec" style={{ paddingTop: 8 }}>
        <div className="page">
          <div className="result-head">
            <h2>{t(lang, "home.mostStores")}</h2>
            <span className="count">
              {lang === "uz"
                ? "kamida 2 do'konda narxi bor modellar"
                : "модели с ценой как минимум в 2 магазинах"}
            </span>
          </div>
          <div className="grid">
            {featured.map((v) => (
              <VariantCard key={v.id} v={v} />
            ))}
          </div>

          <div className="result-head" style={{ marginTop: 40 }}>
            <h2>{t(lang, "home.brands")}</h2>
          </div>
          {(() => {
            const groups = new Map<string, typeof brands>();
            for (const b of brands) {
              const arr = groups.get(b.category) ?? [];
              arr.push(b);
              groups.set(b.category, arr);
            }
            return [...groups.entries()].map(([cat, list]) => (
              <div key={cat} style={{ marginTop: 8 }}>
                <h3 style={{ fontSize: 15, fontWeight: 600, margin: "18px 0 8px" }}>
                  {t(lang, `cat.${cat}` as any)}
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
            ));
          })()}
        </div>
      </section>
    </main>
  );
}