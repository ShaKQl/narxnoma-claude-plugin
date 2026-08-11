"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import VariantCard from "./VariantCard";
import { useLang } from "./LangProvider";
import type { SearchResult, VariantHit } from "@/lib/queries";

/**
 * Backstop only. Appending normally pushes the sentinel out of view, and the
 * observer below acts on its RETURN, so one gesture buys one page. This bounds
 * the pathological case where the appended rows are shorter than the
 * observer's margin and the sentinel therefore never leaves: after this many
 * consecutive loads the reader has to press the button. Restored the moment
 * the sentinel does go out of view.
 */
const AUTO_BUDGET = 4;

/**
 * A results grid that grows as you scroll, over /api/search.
 *
 * THE PAGER STAYS. Infinite scroll has exactly one failure mode that matters:
 * when the fetch breaks, the page simply stops producing goods and looks
 * finished rather than broken. So this renders `pagerFallback` -- the ordinary
 * numbered links the page rendered server-side -- underneath, and a "show
 * more" button that works whether or not the observer ever fires. Nothing here
 * depends on IntersectionObserver being supported, or on scrolling happening
 * at all.
 *
 * The first page is NOT fetched: it is server-rendered and handed in as
 * `initialHits`, so the page is complete and indexable before any JavaScript
 * runs, and the scroll only ever appends page 2 onward.
 */
export default function InfiniteGrid({
  initialHits,
  initialPage,
  pages,
  total,
  qs,
  pagerFallback,
  onLoaded,
}: {
  initialHits: VariantHit[];
  initialPage: number;
  pages: number;
  total: number;
  /** Query string for /api/search WITHOUT `page`. */
  qs: string;
  /** The server-rendered numbered pager, kept as the manual fallback. */
  pagerFallback?: React.ReactNode;
  /** Told the running total, for a heading that counts what is on screen. */
  onLoaded?: (shown: number) => void;
}) {
  const lang = useLang();
  const [hits, setHits] = useState<VariantHit[]>(initialHits);
  const [page, setPage] = useState(initialPage);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const sentinel = useRef<HTMLDivElement | null>(null);
  /** Which result set the in-flight request belongs to. */
  const wantQs = useRef(qs);
  wantQs.current = qs;
  /** Backstop for a sentinel that never leaves view; see AUTO_BUDGET. */
  const autoLeft = useRef(AUTO_BUDGET);
  /** Previous intersection state, so we can act on the rising edge only. */
  const wasVisible = useRef(false);

  // A filter, sort or query change hands down a new first page. Replace
  // rather than append -- appending across two different result sets is how
  // an infinite list starts showing a mixture nobody asked for.
  //
  // Keyed on the IDENTITY of initialHits, not on `qs`. Keying it on qs was
  // wrong in a way worth recording: the parent sets the new query string
  // immediately and the new rows only arrive when the fetch resolves, so the
  // reset fired on the render that still carried the OLD rows, and the render
  // that finally carried the new ones was skipped as "same qs". Changing the
  // sort updated the URL and the active chip while the products underneath
  // stayed exactly as they were.
  useEffect(() => {
    setHits(initialHits);
    setPage(initialPage);
    setFailed(false);
    autoLeft.current = AUTO_BUDGET;
  }, [initialHits, initialPage]);

  useEffect(() => {
    onLoaded?.(hits.length);
  }, [hits.length, onLoaded]);

  const more = useCallback(
    async (auto: boolean) => {
      if (loading || page >= pages) return;
      if (auto && autoLeft.current <= 0) return;
      if (auto) autoLeft.current -= 1;
      else autoLeft.current = AUTO_BUDGET; // a click re-arms the automatic run
      setLoading(true);
      setFailed(false);
      const want = page + 1;
      const forQs = qs;
      try {
        const r = await fetch(`/api/search?${qs}&page=${want}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = (await r.json()) as SearchResult;
        if (wantQs.current !== forQs) return; // filters moved on; drop it
        setHits((prev) => {
          // The catalogue moves under us between requests, so page N+1 can
          // repeat a row from page N. De-duplicate by id rather than trusting
          // OFFSET to be stable.
          const seen = new Set(prev.map((h) => h.id));
          return [...prev, ...j.hits.filter((h) => !seen.has(h.id))];
        });
        setPage(want);
      } catch {
        setFailed(true);
      } finally {
        setLoading(false);
      }
    },
    [loading, page, pages, qs]
  );

  useEffect(() => {
    const node = sentinel.current;
    if (!node || page >= pages || failed) return;
    if (typeof IntersectionObserver === "undefined") return; // button still works
    const io = new IntersectionObserver(
      (entries) => {
        const now = entries[entries.length - 1].isIntersecting;
        const was = wasVisible.current;
        wasVisible.current = now;
        // ONE load per arrival, on the rising edge only.
        //
        // Firing on `isIntersecting` alone reads as "the end is near", which
        // stays true after the append: the observer refires as fast as the
        // API answers and one flick to the bottom becomes a burst. Measured
        // on /c/televisions, that pulled 840 products and 35 requests in a
        // few seconds. It also cannot be fixed by re-arming on scroll --
        // scrolling fires continuously and just refills whatever budget it
        // is guarding.
        //
        // The honest signal is the sentinel ARRIVING. It can only arrive
        // again after the rows just appended have pushed it back out of
        // view, which is exactly "the reader got to the bottom again".
        if (now && !was) more(true);
        if (!now) autoLeft.current = AUTO_BUDGET; // left view: budget restored
      },
      // Fetch a little before the sentinel is on screen, so the next rows are
      // usually there by the time the reader arrives.
      { rootMargin: "300px 0px" }
    );
    io.observe(node);
    return () => io.disconnect();
  }, [more, page, pages, failed]);

  const done = page >= pages;
  const label = failed
    ? lang === "uz" ? "Qayta urinish" : "Повторить"
    : loading
      ? lang === "uz" ? "Yuklanmoqda…" : "Загружаем…"
      : lang === "uz" ? "Yana ko'rsatish" : "Показать ещё";

  return (
    <>
      <div className="grid">
        {hits.map((v) => (
          <VariantCard key={v.id} v={v} />
        ))}
      </div>

      {!done && <div ref={sentinel} aria-hidden="true" style={{ height: 1 }} />}

      {!done && (
        <div className="more-row">
          <button
            type="button"
            className="more-btn"
            onClick={() => more(false)}
            disabled={loading}
          >
            {label}
          </button>
          <span className="count">
            {hits.length} / {total}
          </span>
        </div>
      )}

      {failed && (
        <div className="banner">
          {lang === "uz"
            ? "Keyingi sahifani yuklab bo'lmadi — quyidagi sahifa raqamlaridan foydalaning."
            : "Не удалось подгрузить следующую страницу — воспользуйтесь номерами страниц ниже."}
        </div>
      )}

      {pagerFallback}
    </>
  );
}
