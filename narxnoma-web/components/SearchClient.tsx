"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Facets from "./Facets";
import InfiniteGrid from "./InfiniteGrid";
import SearchBox from "./SearchBox";
import { useLang } from "./LangProvider";
import { plural, t } from "@/lib/i18n";
import type { SearchResult } from "@/lib/queries";

const SORTS = ["relevance", "price_asc", "price_desc", "stores"] as const;

/**
 * SSR-first search: the server renders `initialResult` (SEO + first paint),
 * then this component takes over. A query, facet or sort change fetches
 * /api/search and swaps the results without a full navigation; the URL is
 * updated in place so the view stays shareable.
 */
export default function SearchClient({
  initialResult,
  initialQs,
  initialRawQ,
  resumeTyping = false,
}: {
  initialResult: SearchResult;
  initialQs: string;
  initialRawQ: string;
  resumeTyping?: boolean;
}) {
  const lang = useLang();
  const [res, setRes] = useState<SearchResult>(initialResult);
  const [qs, setQs] = useState(initialQs);
  const [rawQ, setRawQ] = useState(initialRawQ);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0); // drop out-of-order responses

  // A server render for a NEW url must win over whatever we are holding.
  // useState only reads its argument on mount, so without this a soft
  // navigation to /search?q=… re-renders the server component and leaves this
  // component showing the previous query's results.
  useEffect(() => {
    setRes(initialResult);
    setQs(initialQs);
    setRawQ(initialRawQ);
    seq.current += 1; // cancel anything in flight for the old url
  }, [initialResult, initialQs, initialRawQ]);

  const apply = useCallback(async (nextQs: string) => {
    const id = ++seq.current;
    // history.replaceState (not router.replace): a client navigation from
    // router.replace suspends the route transition and leaves the fetch and
    // this component stuck (observed: loading never clears, URL never
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
  }, []);

  // Re-sync if the user navigates (back/forward) to a different query string.
  useEffect(() => {
    const sync = () => {
      const q = window.location.search.replace(/^\?/, "");
      if (q !== qs) {
        setQs(q);
        setRawQ(new URLSearchParams(q).get("q") ?? "");
        fetch(`/api/search?${q}`)
          .then((r) => r.json())
          .then((j) => setRes(j as SearchResult))
          .catch(() => {});
      }
    };
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, [qs]);

  const qsFor = useCallback(
    (patch: Record<string, string | null>) => {
      const sp = new URLSearchParams(qs);
      for (const [k, v] of Object.entries(patch)) {
        if (v == null || v === "") sp.delete(k);
        else sp.set(k, v);
      }
      sp.delete("page"); // any change resets paging
      return sp.toString();
    },
    [qs]
  );

  // Every keystroke (debounced inside SearchBox) rewrites ?q= and refetches,
  // so the address bar always describes what is on screen.
  const onQuery = useCallback(
    (typed: string) => {
      if (typed === rawQ) return;
      setRawQ(typed);
      apply(qsFor({ q: typed || null }));
    },
    [apply, qsFor, rawQ]
  );

  // The grid drives its own paging, so it gets the filters without `page`.
  const gridQs = (() => {
    const sp = new URLSearchParams(qs);
    sp.delete("page");
    return sp.toString();
  })();

  const pager =
    res.pages > 1 ? (
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
    ) : null;

  return (
    <>
      <div style={{ padding: "18px 0 4px" }}>
        <SearchBox initial={rawQ} onQuery={onQuery} resumeTyping={resumeTyping} />
      </div>
      <div className="search-layout">
        <details className="facets-mobile">
          <summary>{t(lang, "facet.filters")}</summary>
          <Facets f={res.facets} applied={res.applied} q={qs} onApply={apply} />
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
                ? `«${rawQ}» — ${plural(lang, res.total, "natija", "результат", "результата", "результатов")}`
                : plural(lang, res.total, "model", "модель", "модели", "моделей")}
              {loading && <span className="count"> · {t(lang, "res.updating")}</span>}
            </h2>
            <span className="count">{t(lang, "stat.updated")}</span>
          </div>
          <div className="sort-bar">
            {SORTS.map((key) => (
              <button
                key={key}
                className={res.applied.sort === key ? "on" : ""}
                onClick={() =>
                  apply(qsFor({ sort: key === "relevance" ? null : key }) || "")
                }
                type="button"
              >
                {t(lang, `sort.${key}`)}
              </button>
            ))}
          </div>

          {error && <div className="banner">Не удалось обновить выдачу: {error}</div>}

          {res.hits.length === 0 ? (
            <div className="empty">
              <p>{t(lang, "res.empty", { q: rawQ })}</p>
              <p style={{ marginTop: 8 }}>{t(lang, "res.emptyHint")}</p>
            </div>
          ) : (
            <InfiniteGrid
              initialHits={res.hits}
              initialPage={res.page}
              pages={res.pages}
              total={res.total}
              qs={gridQs}
              pagerFallback={pager}
            />
          )}
        </section>
      </div>
    </>
  );
}
