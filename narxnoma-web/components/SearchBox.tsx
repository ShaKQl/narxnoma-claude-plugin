"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLang } from "./LangProvider";
import { price, t } from "@/lib/i18n";

interface Suggestion {
  slug: string;
  display_name: string;
  min_price: number | null;
  store_count: number;
}

/** How long to wait after the last keystroke before asking the server. */
const DEBOUNCE_MS = 220;

/**
 * The search box.
 *
 * TWO THINGS THIS GOT WRONG, both worth stating because neither is visible
 * from reading the component alone.
 *
 * 1. THE DROPDOWN USED TO OPEN BY ITSELF. Its effect ran on mount, and on
 *    /search the box is pre-filled with the current query, so the effect
 *    fetched suggestions and called setOpen(true) with `document.activeElement`
 *    still BODY -- nobody had focused, clicked or typed anything. The panel is
 *    640x374 and sits directly over the sort bar, so `elementFromPoint` at the
 *    sort buttons returned a suggestion link. Every click meant to change the
 *    sort order landed on a product instead. That is the entire "sort and the
 *    sidebar filters do not work" report: the handlers were always fine, the
 *    clicks never reached them.
 *
 *    So the panel now opens only after a real interaction (`touched`), and
 *    closes on Escape, on pick, and on a click outside.
 *
 * 2. THE URL ONLY CHANGED ON SUBMIT. Typing narrowed nothing until Enter, and
 *    the address bar never reflected what was on screen, so a result could not
 *    be linked or reloaded. `onQuery` now fires on every (debounced) keystroke;
 *    the search page uses it to rewrite ?q= and refetch in place. Without that
 *    prop -- the home page -- the box still navigates on submit, because there
 *    is nothing on the home page to update live.
 */
export default function SearchBox({
  initial = "",
  big = false,
  onQuery,
  resumeTyping = false,
}: {
  initial?: string;
  big?: boolean;
  /** Called with the typed text, debounced. Present only where the page can
   *  re-render results in place. */
  onQuery?: (q: string) => void;
  /** The reader was mid-word on another page; take the caret back. */
  resumeTyping?: boolean;
}) {
  const router = useRouter();
  const lang = useLang();
  const [q, setQ] = useState(initial);
  const [sugg, setSugg] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [brands, setBrands] = useState<string[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrap = useRef<HTMLDivElement | null>(null);
  const input = useRef<HTMLInputElement | null>(null);
  /** False until the user focuses or types. Nothing may open before it. */
  const touched = useRef(false);
  /** Latest onQuery, so the debounce effect need not depend on its identity. */
  const emit = useRef(onQuery);
  emit.current = onQuery;

  // Follow the query when the page itself changes it (back/forward, or a
  // fresh server render). Skipped while the user is typing, so their caret is
  // never yanked out from under them.
  useEffect(() => {
    if (!touched.current) setQ(initial);
  }, [initial]);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (!touched.current) return; // never act on the value we were handed
    const query = q.trim();

    timer.current = setTimeout(async () => {
      if (emit.current) {
        emit.current(query);
      } else if (query.length >= 2) {
        // No results on this page to update in place (the home page), so the
        // only way for the address bar to follow the typing is to go where
        // the results are. Done once, on the way to /search; from there the
        // page updates itself and the URL never navigates again.
        //
        // `?typing=1` asks the search page to focus its box and put the caret
        // at the end, so a word begun here can be finished there. Without it
        // the hop lands on a fresh input and swallows the rest of the word.
        router.push(`/search?q=${encodeURIComponent(query)}&typing=1`);
        return;
      }
      if (query.length < 2) {
        setSugg([]);
        setBrands([]);
        setOpen(false);
        return;
      }
      try {
        const r = await fetch(`/api/suggest?q=${encodeURIComponent(query)}`);
        if (!r.ok) return;
        const j = await r.json();
        setSugg(j.variants ?? []);
        setBrands(j.brands ?? []);
        setOpen((j.variants ?? []).length > 0 || (j.brands ?? []).length > 0);
      } catch {
        /* offline: suggestions are a nicety */
      }
    }, DEBOUNCE_MS);

    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [q, router]);

  // Arriving from the home page mid-word: take the caret back so the rest of
  // the word lands in the box rather than nowhere.
  useEffect(() => {
    if (!resumeTyping) return;
    const el = input.current;
    if (!el) return;
    touched.current = true;
    el.focus();
    const end = el.value.length;
    try {
      el.setSelectionRange(end, end);
    } catch {
      /* type=search does not always allow selection ranges */
    }
  }, [resumeTyping]);

  // Close when the click lands anywhere else. `onBlur` alone was not enough:
  // it never fires for a panel that was opened without focus.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const submit = useCallback(
    (e?: React.FormEvent) => {
      e?.preventDefault();
      const query = q.trim();
      setOpen(false);
      if (onQuery) {
        // The page updates in place; do not navigate out from under it.
        if (timer.current) clearTimeout(timer.current);
        onQuery(query);
        return;
      }
      router.push(query ? `/search?q=${encodeURIComponent(query)}` : "/search");
    },
    [q, router, onQuery]
  );

  return (
    <div className="searchbox-wrap" ref={wrap}>
      <form className="searchbox" onSubmit={submit} role="search">
        <input
          ref={input}
          type="search"
          value={q}
          onChange={(e) => {
            touched.current = true;
            setQ(e.target.value);
          }}
          onFocus={() => {
            touched.current = true;
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") setOpen(false);
          }}
          placeholder={
            lang === "uz"
              ? "Smartfon, model yoki brend — masalan, iPhone 17"
              : "Смартфон, модель или бренд — например, iPhone 17"
          }
          aria-label={t(lang, "search.ph")}
          autoFocus={big}
        />
        <button type="submit">{t(lang, "search.go")}</button>
      </form>
      {open && (sugg.length > 0 || brands.length > 0) && (
        <div className="suggest">
          {brands.length > 0 && (
            <>
              <div className="s-brand">{lang === "uz" ? "Brendlar" : "Бренды"}</div>
              {brands.map((b) => (
                <a key={b} href={`/search?q=${encodeURIComponent(b)}`}>
                  <span className="s-name">{b}</span>
                </a>
              ))}
            </>
          )}
          {sugg.map((s) => (
            <a key={s.slug} href={`/p/${s.slug}`}>
              <span className="s-name">{s.display_name}</span>
              <span className="s-meta">
                {" "}
                · {lang === "uz" ? "dan" : "от"} {price(lang, s.min_price)} ·{" "}
                {s.store_count} {lang === "uz" ? "do'kon" : "магазинов"}
              </span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
