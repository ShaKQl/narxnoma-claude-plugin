import Link from "next/link";
import { cookies } from "next/headers";
import VariantCard from "@/components/VariantCard";
import { langFromCookie, plural, t } from "@/lib/i18n";
import { getBrandsByCategory, searchVariants } from "@/lib/queries";
import { parseSearchParams } from "@/lib/searchParams";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 24;

export default async function CatalogPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const lang = langFromCookie((await cookies()).get("lang")?.value);
  const p = parseSearchParams(sp);
  const category = p.category ?? null;

  const [brandRows, res] = await Promise.all([
    getBrandsByCategory(),
    searchVariants({ ...p, sort: "price_asc", page: Math.max(1, p.page) }),
  ]);

  // Category counts for the filter bar.
  const catCount = new Map<string, number>();
  for (const b of brandRows) catCount.set(b.category, (catCount.get(b.category) ?? 0) + Number(b.count));
  const categories = ["smartphones", "televisions", "laptops", "acs", "fridges", "washers", "ovens"];

  const label = (c: string) => {
    const v = t(lang, `cat.${c}`);
    return v && !v.startsWith("cat.") ? v : c;
  };

  return (
    <main>
      <div className="page">
        <section className="sec">
          <h1>{category ? label(category) : t(lang, "catalog.title")}</h1>

          {/* Category filter bar: switch category at any moment. */}
          <div className="cat-filter" role="group" aria-label="categories">
            {categories.map((c) => {
              const active = c === category;
              return (
                <Link
                  key={c}
                  href={active ? "/catalog" : `/catalog?category=${c}`}
                  className={`cat-chip${active ? " active" : ""}`}
                  aria-current={active ? "page" : undefined}
                >
                  {label(c)}
                  <span className="chip-n">{catCount.get(c) ?? 0}</span>
                </Link>
              );
            })}
          </div>

          <p className="sub">
            {res.total > 0
              ? `${plural(lang, res.total, "model", "модель", "модели", "моделей")} ${
                  lang === "uz" ? "katalogda" : "в каталоге"
                }`
              : lang === "uz" ? "Hozircha bo'sh." : "Пока пусто."}
          </p>

          <div className="grid">
            {res.hits.map((v) => (
              <VariantCard key={v.id} v={v} />
            ))}
          </div>

          {res.pages > 1 && (
            <nav className="pagination" aria-label="pagination">
              {p.page > 1 && (
                <Link href={`/catalog?category=${category ?? ""}&page=${p.page - 1}`} rel="prev">
                  ←
                </Link>
              )}
              {Array.from({ length: res.pages }, (_, i) => i + 1)
                .filter((n) => n === 1 || n === res.pages || Math.abs(n - p.page) <= 2)
                .map((n, idx, arr) => (
                  <span key={n} style={{ display: "inline-flex", gap: 4 }}>
                    {idx > 0 && arr[idx - 1] !== n - 1 ? <span className="pg-ellipsis">…</span> : null}
                    <Link
                      href={`/catalog?category=${category ?? ""}&page=${n}`}
                      className={n === p.page ? "cur" : ""}
                      aria-current={n === p.page ? "page" : undefined}
                    >
                      {n}
                    </Link>
                  </span>
                ))}
              {p.page < res.pages && (
                <Link href={`/catalog?category=${category ?? ""}&page=${p.page + 1}`} rel="next">
                  →
                </Link>
              )}
            </nav>
          )}
        </section>
      </div>
    </main>
  );
}