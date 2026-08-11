import Link from "next/link";
import { cookies } from "next/headers";
import InfiniteGrid from "@/components/InfiniteGrid";
import Pager from "@/components/Pager";
import { langFromCookie, plural, t } from "@/lib/i18n";
import { getBrandsByCategory, searchVariants } from "@/lib/queries";
import { parseSearchParams } from "@/lib/searchParams";

export const dynamic = "force-dynamic";

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

  // What InfiniteGrid appends must be the SAME query the server just ran, so
  // the filters and the sort are carried and `page` is left for the grid.
  const grid = new URLSearchParams();
  if (category) grid.set("category", category);
  grid.set("sort", "price_asc");
  const gridQs = grid.toString();

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

          {/* Scrolling appends the next page; the numbered links below stay
              as the manual route, and are what a crawler (and a browser with
              a broken fetch) follows. */}
          <InfiniteGrid
            initialHits={res.hits}
            initialPage={res.page}
            pages={res.pages}
            total={res.total}
            qs={gridQs}
            pagerFallback={
              <Pager
                page={res.page}
                pages={res.pages}
                basePath="/catalog"
                query={{ category: category ?? undefined }}
              />
            }
          />
        </section>
      </div>
    </main>
  );
}