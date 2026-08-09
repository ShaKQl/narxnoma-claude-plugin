import Link from "next/link";
import SearchBox from "@/components/SearchBox";
import VariantCard from "@/components/VariantCard";
import { formatPrice, pluralRu, timeAgoRu } from "@/lib/format";
import { getBrandsByCategory, getFeatured, getHomeStats } from "@/lib/queries";

export const revalidate = 300;

export default async function HomePage() {
  const [stats, featured, brands] = await Promise.all([
    getHomeStats(),
    getFeatured(),
    getBrandsByCategory(),
  ]);

  return (
    <main>
      <section className="hero">
        <h1>Сравните цены на смартфон в 7 магазинах Узбекистана</h1>
        <p className="sub">
          Введите название модели — и мы покажем, кто продаёт её дешевле: Uzum,
          Alif Shop, BeeMarket, Idea, Mediapark, Olcha или Texnomart. Рядом с
          каждой ценой — формулировка самого магазина, чтобы вы могли проверить
          совпадение.
        </p>
        <SearchBox big />
        <div className="stat-strip">
          <div className="stat">
            <span className="num">{stats.variants_priced}</span>
            <span className="lbl">
              {pluralRu(stats.variants_priced, "модель", "модели", "моделей")}
            </span>
          </div>
          <div className="stat">
            <span className="num">{stats.stores}</span>
            <span className="lbl">
              {pluralRu(stats.stores, "магазин", "магазина", "магазинов")}
            </span>
          </div>
          <div className="stat">
            <span className="num">{stats.last_updated ? timeAgoRu(stats.last_updated) : "—"}</span>
            <span className="lbl">проверка цен</span>
          </div>
        </div>
      </section>

      <section className="sec" style={{ paddingTop: 8 }}>
        <div className="page">
          <div className="result-head">
            <h2>Где больше всего магазинов</h2>
            <span className="count">модели с ценой как минимум в 2 магазинах</span>
          </div>
          <div className="grid">
            {featured.map((v) => (
              <VariantCard key={v.id} v={v} />
            ))}
          </div>

          <div className="result-head" style={{ marginTop: 40 }}>
            <h2>Каталог по брендам</h2>
          </div>
          <div className="brand-grid">
            {brands.map((b) => (
              <Link
                key={b.brand}
                className="brand-tile"
                href={`/c/${b.category}/${b.brand}`}
              >
                <span className="b-name">{b.brand}</span>
                <span className="b-meta">
                  {pluralRu(b.count, "модель", "модели", "моделей")}
                  {b.min_price != null && ` · от ${formatPrice(b.min_price)}`}
                </span>
              </Link>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}