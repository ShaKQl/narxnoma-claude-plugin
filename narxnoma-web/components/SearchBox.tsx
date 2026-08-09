"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { formatPrice } from "@/lib/format";

interface Suggestion {
  slug: string;
  display_name: string;
  min_price: number | null;
  store_count: number;
}

export default function SearchBox({
  initial = "",
  big = false,
}: {
  initial?: string;
  big?: boolean;
}) {
  const router = useRouter();
  const [q, setQ] = useState(initial);
  const [sugg, setSugg] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [brands, setBrands] = useState<string[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    const query = q.trim();
    if (query.length < 2) {
      setSugg([]);
      setBrands([]);
      return;
    }
    timer.current = setTimeout(async () => {
      try {
        const r = await fetch(`/api/suggest?q=${encodeURIComponent(query)}`);
        if (!r.ok) return;
        const j = await r.json();
        setSugg(j.variants ?? []);
        setBrands(j.brands ?? []);
        setOpen(true);
      } catch {
        /* offline: suggestions are a nicety */
      }
    }, 150);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [q]);

  const submit = useCallback(
    (e?: React.FormEvent) => {
      e?.preventDefault();
      const query = q.trim();
      setOpen(false);
      router.push(query ? `/search?q=${encodeURIComponent(query)}` : "/search");
    },
    [q, router]
  );

  return (
    <div className="searchbox-wrap">
      <form className="searchbox" onSubmit={submit} role="search">
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onFocus={() => q.trim().length >= 2 && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Смартфон, модель или бренд — например, iPhone 17"
          aria-label="Название товара"
          autoFocus={big}
        />
        <button type="submit">Найти</button>
      </form>
      {open && (sugg.length > 0 || brands.length > 0) && (
        <div className="suggest">
          {brands.length > 0 && (
            <>
              <div className="s-brand">Бренды</div>
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
                · от {formatPrice(s.min_price)} · {s.store_count} магазинов
              </span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}