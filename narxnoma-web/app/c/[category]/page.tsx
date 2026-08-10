import type { Metadata } from "next";
import Link from "next/link";
import { cookies } from "next/headers";
import { langFromCookie, plural, price, t } from "@/lib/i18n";
import { getBrandsByCategory } from "@/lib/queries";

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
  const rows = (await getBrandsByCategory()).filter(
    (r) => r.category === category
  );
  const catLabel = (c: string) =>
    c === "smartphones" ? t(lang, "cat.smartphones") : c;
  return (
    <main>
      <div className="page">
        <section className="sec">
          <h1>{catLabel(category)}</h1>
          <p className="sub">
            {plural(lang, rows.length, "brend", "бренд", "бренда", "брендов")} —{" "}
            {lang === "uz"
              ? "O'zbekistonning 7 do'konidagi narxlar, har biri avtomatik tekshiriladi."
              : "цены из 7 магазинов Узбекистана, каждая проверяется автоматически."}
          </p>
          <div className="brand-grid">
            {rows.map((b) => (
              <Link
                key={b.brand}
                className="brand-tile"
                href={`/c/${category}/${b.brand}`}
              >
                <span className="b-name">{b.brand}</span>
                <span className="b-meta">
                  {plural(lang, b.count, "model", "модель", "модели", "моделей")}
                  {b.min_price != null &&
                    ` · ${lang === "uz" ? "dan" : "от"} ${price(lang, b.min_price)}`}
                </span>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}