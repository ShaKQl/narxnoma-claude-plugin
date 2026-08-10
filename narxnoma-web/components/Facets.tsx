"use client";

import { COLORS, colorRu } from "@/lib/colors";
import { price, t } from "@/lib/i18n";
import { useLang } from "./LangProvider";
import type { SearchResult } from "@/lib/queries";

function toggle(list: string[], v: string): string[] {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

/**
 * Facet sidebar. No navigation of its own: every toggle builds the next URL
 * query string and hands it to onApply (the parent fetches + updates the URL),
 * keeping the checkbox experience instant. `q` is the CURRENT query string.
 */
export default function Facets({
  f,
  applied,
  q,
  onApply,
  className = "",
}: {
  f: SearchResult["facets"];
  applied: SearchResult["applied"];
  q: string;
  onApply: (nextQs: string) => void;
  className?: string;
}) {
  const sp = new URLSearchParams(q);
  const lang = useLang();

  const patch = (p: Record<string, string | null>) => {
    for (const [k, v] of Object.entries(p)) {
      if (v == null || v === "") sp.delete(k);
      else sp.set(k, v);
    }
    sp.delete("page");
    onApply(sp.toString());
  };

  const activeBrands = sp.getAll("brand").flatMap((x) => x.split(",")).filter(Boolean);
  const activeColors = sp.getAll("color").flatMap((x) => x.split(",")).filter(Boolean);
  const activeRams = sp.getAll("ram").flatMap((x) => x.split(",")).filter(Boolean);
  const activePrice = sp.get("price");

  const setBrand = (b: string) =>
    patch({ brand: toggle(activeBrands, b).join(",") });
  const setColor = (c: string) =>
    patch({ color: toggle(activeColors, c).join(",") });
  const setRam = (r: string) => {
    const key = r === "none" ? "none" : r;
    patch({ ram: toggle(activeRams, key).join(",") });
  };
  const setBand = (lo: number) =>
    patch({ price: activePrice === String(lo) ? null : String(lo) });
  const setMulti = () => patch({ multi: applied.multiStore ? null : "1" });

  return (
    <aside className={`facets ${className}`.trim()}>
      <div className="facet-group">
        <h3>{t(lang, "facet.onlyComparable")}</h3>
        <label className="facet-row">
          <input type="checkbox" checked={applied.multiStore} onChange={setMulti} />
          <span className="f-label">{t(lang, "facet.multi")}</span>
        </label>
      </div>

      <div className="facet-group">
        <h3>{t(lang, "facet.brand")}</h3>
        {f.brands.map((b) => (
          <label className="facet-row" key={b.value}>
            <input
              type="checkbox"
              checked={activeBrands.includes(String(b.value))}
              onChange={() => setBrand(String(b.value))}
            />
            <span className="f-label">{String(b.value)}</span>
            <span className="f-count">{b.count}</span>
          </label>
        ))}
      </div>

      <div className="facet-group">
        <h3>{t(lang, "facet.color")}</h3>
        {f.colors.map((c) => {
          const key = String(c.value);
          return (
            <label className="facet-row" key={key}>
              <input
                type="checkbox"
                checked={activeColors.includes(key)}
                onChange={() => setColor(key)}
              />
              <span className={`facet-swatch sw-${key}`} />
              <span className="f-label">{colorRu(key)}</span>
              <span className="f-count">{c.count}</span>
            </label>
          );
        })}
      </div>

      <div className="facet-group">
        <h3>{t(lang, "facet.ram")}</h3>
        {f.rams.map((r) => {
          const key = r == null ? "none" : String(r);
          return (
            <label className="facet-row" key={key}>
              <input
                type="checkbox"
                checked={activeRams.includes(key)}
                onChange={() => setRam(key)}
              />
              <span className="f-label">
                {r == null ? t(lang, "facet.none") : `${r} ГБ`}
              </span>
              <span className="f-count">{f.ramCounts[key] ?? 0}</span>
            </label>
          );
        })}
      </div>

      {f.priceBands.length > 0 && (
        <div className="facet-group">
          <h3>{t(lang, "facet.price")}</h3>
          {f.priceBands.map((b) => (
            <label className="facet-row" key={b.lo}>
              <input
                type="checkbox"
                checked={activePrice === String(b.lo)}
                onChange={() => setBand(b.lo)}
              />
              <span className="f-label">
                {price(lang, b.lo)} — {price(lang, b.hi)}
              </span>
              <span className="f-count">{b.count}</span>
            </label>
          ))}
        </div>
      )}

      {COLORS.length > 0 && (
        <div className="facet-group" style={{ display: "none" }}>
          <h3>Цвет</h3>
        </div>
      )}
    </aside>
  );
}