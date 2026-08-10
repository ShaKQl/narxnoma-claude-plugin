"use client";

import Link from "next/link";
import { useLang } from "./LangProvider";
import { plural, t } from "@/lib/i18n";

export interface CategoryRow {
  category: string;
  count: number;
  stores: number;
  min_price: number | null;
}

/**
 * A broad, Uzum/Amazon-style category grid. Renders every category the
 * catalogue actually has products in, so the site leads with the whole range
 * of goods rather than a single category. Icons are inline-SVG light glyphs
 * (no dependency), one per category.
 */
const ICONS: Record<string, string> = {
  smartphones:
    "M4 7h16v10H4zM8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M12 11v2",
  televisions:
    "M4 5h16v11H4zM8 20h8M12 16v4",
  laptops:
    "M4 6h16v9H4zM2 19h20M9 6v1M15 6v1",
  acs:
    "M4 8h16a1 1 0 0 1 1 1v7H3V9a1 1 0 0 1 1-1zM7 3h10M12 3v5M6 16l-2 4M18 16l2 4",
  fridges:
    "M5 3h14v18H5zM9 3v18M9 8h.01M9 13h.01M9 17h.01",
  washers:
    "M5 3h14v18H5zM9 8h6M9 15a2 2 0 1 0 0-.01",
  ovens:
    "M4 7h16a1 1 0 0 1 1 1v9H3V8a1 1 0 0 1 1-1zM7 7V4M12 7V4M17 7V4M7 12h10",
};

export default function CategoryGrid({
  rows,
  columns = 4,
}: {
  rows: CategoryRow[];
  columns?: number;
}) {
  const lang = useLang();
  return (
    <div
      className="cat-grid"
      style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}
    >
      {rows.map((r) => (
        <Link key={r.category} className="cat-tile" href={`/c/${r.category}`}>
          <span className="cat-icon" aria-hidden="true">
            <svg
              viewBox="0 0 24 24"
              width="26"
              height="26"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d={ICONS[r.category] ?? ICONS.smartphones} />
            </svg>
          </span>
          <span className="cat-body">
            <span className="cat-name">{t(lang, `cat.${r.category}`)}</span>
            <span className="cat-meta">
              {plural(lang, r.count, "model", "модель", "модели", "моделей")}
              {r.min_price != null &&
                ` · ${lang === "uz" ? "dan" : "от"} ${Intl.NumberFormat(lang === "uz" ? "uz-UZ" : "ru-RU").format(
                  Math.round(r.min_price)
                )} ${lang === "uz" ? "so'm" : "сум"}`}
            </span>
          </span>
        </Link>
      ))}
    </div>
  );
}