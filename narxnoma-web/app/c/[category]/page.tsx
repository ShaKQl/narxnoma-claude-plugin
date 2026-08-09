import type { Metadata } from "next";
import Link from "next/link";
import { formatPrice, pluralRu } from "@/lib/format";
import { getBrandsByCategory } from "@/lib/queries";

export const revalidate = 300;

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
  const rows = (await getBrandsByCategory()).filter(
    (r) => r.category === category
  );
  return (
    <main>
      <div className="page">
        <section className="sec">
          <h1>{category === "smartphones" ? "Смартфоны" : category}</h1>
          <p className="sub">
            {pluralRu(rows.length, "бренд", "бренда", "брендов")} — цены из 7
            магазинов Узбекистана, каждая проверяется автоматически.
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
                  {pluralRu(b.count, "модель", "модели", "моделей")}
                  {b.min_price != null && ` · от ${formatPrice(b.min_price)}`}
                </span>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}