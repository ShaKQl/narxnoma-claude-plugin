import type { Metadata } from "next";
import Link from "next/link";
import { cookies } from "next/headers";
import VariantCard from "@/components/VariantCard";
import { langFromCookie, plural, price, t } from "@/lib/i18n";
import { getBrandsByCategory, searchVariants } from "@/lib/queries";

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ category: string; brand: string }>;
}): Promise<Metadata> {
  const { brand } = await params;
  return { title: brand.charAt(0).toUpperCase() + brand.slice(1) };
}

export default async function BrandPage({
  params,
}: {
  params: Promise<{ category: string; brand: string }>;
}) {
  const { category, brand } = await params;
  const lang = langFromCookie((await cookies()).get("lang")?.value);
  const res = await searchVariants({
    qNorm: brand,
    brands: [brand],
    colors: [],
    rams: [],
    priceLo: null,
    priceHi: null,
    multiStore: false,
    category,
    sort: "relevance",
    page: 1,
  });
  const counts = (await getBrandsByCategory()).filter(
    (r) => r.category === category && r.brand === brand
  );
  const c = counts[0];
  return (
    <main>
      <div className="page">
        <section className="sec">
          <div className="breadcrumbs" style={{ paddingTop: 0 }}>
            <a href="/">{lang === "uz" ? "Bosh sahifa" : "Главная"}</a>
            {" · "}
            <a href={`/c/${category}`}>
              {category === "smartphones" ? t(lang, "cat.smartphones") : category}
            </a>
          </div>
          <h1 style={{ textTransform: "capitalize" }}>{brand}</h1>
          <p className="sub">
            {c
              ? `${plural(lang, c.count, "model", "модель в каталоге", "модели в каталоге", "моделей в каталоге")} · ${lang === "uz" ? "dan" : "от"} ${price(lang, c.min_price)}`
              : lang === "uz"
                ? "Katalogdagi modellar."
                : "Модели из каталога."}
          </p>
          <div className="grid">
            {res.hits.map((v) => (
              <VariantCard key={v.id} v={v} />
            ))}
          </div>
          {res.hits.length > 24 && (
            <div style={{ marginTop: 24 }}>
              <Link href={`/search?brand=${brand}`} style={{ textDecoration: "underline" }}>
                {lang === "uz"
                  ? `Barcha ${brand} modellarini ko'rsatish →`
                  : `Показать все модели ${brand} →`}
              </Link>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}