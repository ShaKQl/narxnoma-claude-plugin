"use client";

import { useRouter } from "next/navigation";
import { COLORS, colorRu } from "@/lib/colors";
import { formatPrice } from "@/lib/format";
import type { SearchResult } from "@/lib/queries";

function toggle(list: string[], v: string): string[] {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

export default function Facets({
  f,
  applied,
  q,
}: {
  f: SearchResult["facets"];
  applied: SearchResult["applied"];
  q: string;
}) {
  const router = useRouter();

  const push = (next: URLSearchParams) => {
    next.set("page", "1");
    const s = next.toString();
    router.push(`/search?${s}`, { scroll: false });
  };

  const sp = new URLSearchParams(q);
  if (applied.multiStore) sp.set("multi", "1");
  else sp.delete("multi");
  if (applied.sort !== "relevance") sp.set("sort", applied.sort);
  else sp.delete("sort");

  const setBrand = (b: string) => {
    sp.set("brand", toggle(sp.getAll("brand"), b).join(","));
    push(sp);
  };
  const setColor = (c: string) => {
    sp.set("color", toggle(sp.getAll("color"), c).join(","));
    push(sp);
  };
  const setRam = (r: string) => {
    sp.set("ram", toggle(sp.getAll("ram"), r).join(","));
    push(sp);
  };
  const setBand = (lo: number) => {
    const cur = sp.get("price");
    if (cur === String(lo)) sp.delete("price");
    else sp.set("price", String(lo));
    push(sp);
  };
  const setMulti = () => {
    if (applied.multiStore) sp.delete("multi");
    else sp.set("multi", "1");
    push(sp);
  };

  const activeBrands = sp.getAll("brand").flatMap((x) => x.split(",")).filter(Boolean);
  const activeColors = sp.getAll("color").flatMap((x) => x.split(",")).filter(Boolean);
  const activeRams = sp.getAll("ram").flatMap((x) => x.split(",")).filter(Boolean);

  return (
    <aside className="facets">
      <div className="facet-group">
        <h3>Только сравнимые</h3>
        <label className="facet-row">
          <input type="checkbox" checked={applied.multiStore} onChange={setMulti} />
          <span className="f-label">2+ магазина</span>
        </label>
      </div>

      <div className="facet-group">
        <h3>Бренд</h3>
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
        <h3>Цвет</h3>
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
        <h3>Оперативная память</h3>
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
                {r == null ? "не указана" : `${r} ГБ`}
              </span>
              <span className="f-count">{f.ramCounts.get(key) ?? 0}</span>
            </label>
          );
        })}
      </div>

      {f.priceBands.length > 0 && (
        <div className="facet-group">
          <h3>Цена</h3>
          {f.priceBands.map((b) => (
            <label className="facet-row" key={b.lo}>
              <input
                type="checkbox"
                checked={sp.get("price") === String(b.lo)}
                onChange={() => setBand(b.lo)}
              />
              <span className="f-label">
                {formatPrice(b.lo)} — {formatPrice(b.hi)}
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