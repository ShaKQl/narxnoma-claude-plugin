import type { Metadata } from "next";
import Link from "next/link";
import { cookies } from "next/headers";
import VariantCard from "@/components/VariantCard";
import { langFromCookie, plural, t } from "@/lib/i18n";
import { getBrandsByCategory, getFeaturedPerCategory } from "@/lib/queries";

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ category: string }>;
}): Promise<Metadata> {
  const { category } = await params;
  return { title: category === "smartphones" ? "Смартфоны" : category };
}

export default async function CategoryPage({
  params,
}: {
  params: Promise<{ category: string }>;
}) {
  const { category } = await params;
  const lang = langFromCookie((await cookies()).get("lang")?.value);
  const [perCategory, brandRows] = await Promise.all([
    getFeaturedPerCategory(8),
    getBrandsByCategory(),
  ]);
  const rows = brandRows.filter((r) => r.category === category);
  const featured = (perCategory.find((g) => g.category === category)?.hits ?? []).slice(0, 8);
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

          {featured.length > 0 && (
            <>
              <div className="row-head" style={{ marginTop: 12 }}>
                <h2 style={{ fontSize: 17, fontWeight: 700 }}>
                  {lang === "uz" ? `Ommabop ${catLabel(category).toLowerCase()}` : `Популярные ${catLabel(category).toLowerCase()}`}
                </h2>
                <Link href={`/search?category=${category}`} className="more-link">
                  {lang === "uz" ? "Barchasini ko'rish →" : "Смотреть все →"}
                </Link>
              </div>
              <div className="grid">
                {featured.map((v) => (
                  <VariantCard key={v.id} v={v} />
                ))}
              </div>
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