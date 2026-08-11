import type { Metadata } from "next";
import Link from "next/link";
import { cookies } from "next/headers";
import InfiniteGrid from "@/components/InfiniteGrid";
import Pager from "@/components/Pager";
import { langFromCookie, plural, t } from "@/lib/i18n";
import { getBrandsByCategory, searchVariants } from "@/lib/queries";

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ category: string }>;
}): Promise<Metadata> {
  const { category } = await params;
  // The slug is not a title: a non-phone category rendered as "televisions"
  // in the browser tab and in every search-engine result.
  const RU: Record<string, string> = {
    smartphones: "Смартфоны",
    televisions: "Телевизоры",
    laptops: "Ноутбуки",
    acs: "Кондиционеры",
    fridges: "Холодильники",
    washers: "Стиральные машины",
    ovens: "Духовые шкафы и плиты",
  };
  return { title: `${RU[category] ?? category} — Narxnoma` };
}

export default async function CategoryPage({
  params,
  searchParams,
}: {
  params: Promise<{ category: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { category } = await params;
  const page = Math.max(1, Number((await searchParams).page) || 1);
  const lang = langFromCookie((await cookies()).get("lang")?.value);

  // Was getCategoryProducts(category, 24) with no paging at all -- the page
  // showed the first 24 and offered nothing but a link out to /catalog.
  // searchVariants is what /api/search runs, so scrolling continues the very
  // list the server rendered rather than a subtly different one, and
  // `priced: true` keeps the min_price filter the old query had. Its ordering
  // is the same store_count-first ranking; the only difference is that it no
  // longer breaks ties on in_stock_offer_count before price. That function is
  // now gone rather than left beside this one to drift.
  const [res, brandRows] = await Promise.all([
    searchVariants({
      qNorm: "",
      qTokens: [],
      brands: [],
      colors: [],
      rams: [],
      priceLo: null,
      priceHi: null,
      multiStore: false,
      category,
      priced: true,
      sort: "stores",
      page,
    }),
    getBrandsByCategory(),
  ]);
  const total = res.total;
  const rows = brandRows.filter((r) => r.category === category);
  const gridQs = `category=${encodeURIComponent(category)}&sort=stores&priced=1`;
  const catLabel = (c: string) => {
    const v = t(lang, `cat.${c}`);
    return v && !v.startsWith("cat.") ? v : c;
  };

  return (
    <main>
      <div className="page">
        <section className="sec">
          <div className="breadcrumbs" style={{ paddingTop: 0 }}>
            <a href="/">{lang === "uz" ? "Bosh sahifa" : "Главная"}</a>
            {" · "}
            <span>{catLabel(category)}</span>
          </div>
          <h1>{catLabel(category)}</h1>
          <p className="sub">
            {lang === "uz"
              ? `Narxlar O'zbekistondagi 7 do'konda solishtiriladi, har biri avtomatik tekshiriladi.`
              : "цены из 7 магазинов Узбекистана, каждая проверяется автоматически."}
          </p>

          {res.hits.length > 0 && (
            <>
              <div className="row-head" style={{ marginTop: 12 }}>
                <h2 style={{ fontSize: 17, fontWeight: 700 }}>
                  {plural(lang, total, "mahsulot", "товар", "товара", "товаров")}
                </h2>
                <Link href={`/catalog?category=${category}`} className="more-link">
                  {lang === "uz" ? "Barchasini ko'rish →" : "Смотреть все →"}
                </Link>
              </div>
              <InfiniteGrid
                initialHits={res.hits}
                initialPage={res.page}
                pages={res.pages}
                total={total}
                qs={gridQs}
                pagerFallback={
                  <Pager page={res.page} pages={res.pages} basePath={`/c/${category}`} />
                }
              />
            </>
          )}

          <div className="result-head" style={{ marginTop: 28 }}>
            <h2>{lang === "uz" ? "Brend bo'yicha" : "По брендам"}</h2>
          </div>
          {rows.length ? (
            <div className="brand-grid">
              {rows.map((b) => (
                <Link
                  key={b.brand}
                  className="brand-tile"
                  href={`/c/${b.category}/${b.brand}`}
                >
                  <span className="b-name">{b.brand}</span>
                  <span className="b-meta">
                    {plural(lang, b.count, "model", "модель", "модели", "моделей")}
                  </span>
                </Link>
              ))}
            </div>
          ) : (
            <p className="sub">{lang === "uz" ? "Hozircha bo'sh." : "Пока пусто."}</p>
          )}
        </section>
      </div>
    </main>
  );
}