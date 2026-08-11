import Link from "next/link";

/**
 * Numbered page links — the manual route that stays available underneath the
 * scroll-appended grid.
 *
 * A component rather than inline JSX in each page, for two reasons. It was
 * duplicated verbatim in /catalog and /c/[category]; and passing this markup
 * inline as a prop from a server component into the client `InfiniteGrid`
 * made React warn about missing keys on every load. The children of the
 * `<nav>` are a static list (`{prev}{numbers}{next}`), which React normally
 * exempts from the key rule via a flag set at JSX-creation time — a flag that
 * does not survive being serialised across the server/client boundary and
 * rebuilt. Handing over one already-rendered element instead of a children
 * array sidesteps the question rather than papering over it with keys that
 * the markup does not otherwise need.
 */
export default function Pager({
  page,
  pages,
  basePath,
  query = {},
}: {
  page: number;
  pages: number;
  /** e.g. "/catalog" or "/c/televisions" */
  basePath: string;
  /** Filters to carry on every page link. `page` is added here. */
  query?: Record<string, string | undefined>;
}) {
  if (pages <= 1) return null;

  const href = (n: number) => {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) if (v) sp.set(k, v);
    sp.set("page", String(n));
    return `${basePath}?${sp.toString()}`;
  };

  // First, last, and a window of two either side of the current page.
  const shown = Array.from({ length: pages }, (_, i) => i + 1).filter(
    (n) => n === 1 || n === pages || Math.abs(n - page) <= 2
  );

  return (
    <nav className="pagination" aria-label="pagination">
      {page > 1 && (
        <Link href={href(page - 1)} rel="prev">
          ←
        </Link>
      )}
      {shown.map((n, idx) => (
        <span key={n} style={{ display: "inline-flex", gap: 4 }}>
          {idx > 0 && shown[idx - 1] !== n - 1 ? (
            <span className="pg-ellipsis">…</span>
          ) : null}
          <Link
            href={href(n)}
            className={n === page ? "cur" : ""}
            aria-current={n === page ? "page" : undefined}
          >
            {n}
          </Link>
        </span>
      ))}
      {page < pages && (
        <Link href={href(page + 1)} rel="next">
          →
        </Link>
      )}
    </nav>
  );
}
