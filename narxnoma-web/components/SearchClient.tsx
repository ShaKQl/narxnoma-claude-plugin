"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Facets from "./Facets";
import SearchBox from "./SearchBox";
import VariantCard from "./VariantCard";
import { useLang } from "./LangProvider";
import { plural, t } from "@/lib/i18n";
import type { SearchResult } from "@/lib/queries";

const SORTS: { key: string }[] = [
  { key: "relevance" },
  { key: "price_asc" },
  { key: "price_desc" },
  { key: "stores" },
];

/**
 * SSR-first search: the server renders `initialResult` (SEO + first paint),
 * then this component takes over. A facet/sort/page change fetches
 * /api/search and swaps the results without a full navigation; the URL is
 * updated in place so the view stays shareable.
 */
export default function SearchClient({
  initialResult,
  initialQs,
  initialRawQ,
}: {
  initialResult: SearchResult;
  initialQs: string;
  initialRawQ: string;
}) {
  const lang = useLang();
  const [res, setRes] = useState<SearchResult>(initialResult);
  const [qs, setQs] = useState(initialQs);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0); // drop out-of-order responses

  const apply = useCallback(
    async (nextQs: string) => {
      const id = ++seq.current;
      // history.replaceState (not router.replace): a client navigation from
      // router.replace suspends the route transition and leaves the fetch
      // and this component stuck (observed: loading never clears, URL never
      // updates, despite the server returning both 200s). replaceState keeps
      // the URL shareable with zero navigation; results update in place.
      window.history.replaceState(null, "", `/search?${nextQs}`);
      setQs(nextQs);
      setLoading(true);
      setError(null);
      try {
        const r = await fetch(`/api/search?${nextQs}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = (await r.json()) as SearchResult;
        if (seq.current === id) setRes(j);
      } catch (e) {
        if (seq.current === id)
          setError(e instanceof Error ? e.message : "не удалось обновить выдачу");
      } finally {
        if (seq.current === id) setLoading(false);
      }
    },
    []
  );

  // Re-sync if the user navigates (back/forward) to a different query string.
  useEffect(() => {
    const sync = () => {
      const q = window.location.search.replace(/^\?/, "");
      if (q !== qs) {
        setQs(q);
        fetch(`/api/search?${q}`)
          .then((r) => r.json())
          .then((j) => setRes(j as SearchResult))
          .catch(() => {});
      }
    };
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, [qs]);

  const qsFor = (patch: Record<string, string | null>) => {
    const sp = new URLSearchParams(qs);
    for (const [k, v] of Object.entries(patch)) {
      if (v == null || v === "") sp.delete(k);
      else sp.set(k, v);
    }
    sp.delete("page"); // any filter change resets paging
    return sp.toString();
  };

  return (
    <>
      <div style={{ padding: "18px 0 4px" }}>
        <SearchBox initial={initialRawQ} />
      </div>
      <div className="search-layout">
        <details className="facets-mobile">
          <summary>{t(lang, "facet.filters")}</summary>
          <Facets
            f={res.facets}
            applied={res.applied}
            q={qs}
            onApply={apply}
          />
        </details>
        <Facets
          f={res.facets}
          applied={res.applied}
          q={qs}
          onApply={apply}
          className="facets-desktop"
        />
        <section>
          <div className="result-head">
            <h2>
              {res.applied.q
                ? `«${initialRawQ}» — ${plural(lang, res.total, "natija", "результат", "результата", "результатов")}`
                : plural(lang, res.total, "model", "модель", "модели", "моделей")}
              {loading && <span className="count"> · {t(lang, "res.updating")}</span>}
            </h2>
            <span className="count">{t(lang, "stat.updated")}</span>
          </div>
          <div className="sort-bar">
            {SORTS.map((s) => (
              <button
                key={s.key}
                className={res.applied.sort === s.key ? "on" : ""}
                onClick={() =>
                  apply(
                    qsFor({
                      sort: s.key === "relevance" ? null : s.key,
                    }) || ""
                  )
                }
                type="button"
              >
                {t(lang, `sort.${s.key}`)}
              </button>
            ))}
          </div>

          {error && <div className="banner">Не удалось обновить выдачу: {error}</div>}

          {res.hits.length === 0 ? (
            <div className="empty">
              <p>{t(lang, "res.empty", { q: initialRawQ })}</p>
              <p style={{ marginTop: 8 }}>{t(lang, "res.emptyHint")}</p>
            </div>
          ) : (
            <>
              <div className="grid">
                {res.hits.map((v) => (
                  <VariantCard key={v.id} v={v} />
                ))}
              </div>
              {res.pages > 1 && (
                <div className="pager">
                  {Array.from({ length: res.pages }, (_, i) => i + 1)
                    .slice(Math.max(0, res.page - 3), Math.min(res.pages, res.page + 2))
                    .map((p) => (
                      <button
                        key={p}
                        className={p === res.page ? "cur" : ""}
                        onClick={() => apply(qsFor({ page: String(p) }))}
                        type="button"
                      >
                        {p}
                      </button>
                    ))}
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </>
  );
}