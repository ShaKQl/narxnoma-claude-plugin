import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { colorRu } from "@/lib/colors";
import {
  availabilityRu,
  formatPrice,
  pluralRu,
  timeAgoRu,
} from "@/lib/format";
import { getVariantPage } from "@/lib/queries";

const SWATCH_HEX: Record<string, string> = {
  black: "#211c16",
  white: "#f7f3ea",
  silver: "#c9c4ba",
  gray: "#8b877f",
  gold: "#c9a43e",
  blue: "#3b5f8a",
  red: "#a63a2e",
  brown: "#7a5a3e",
  green: "#4c7a52",
  purple: "#6d4c8a",
  orange: "#c0702f",
  pink: "#c98a9a",
  beige: "#d9c9a8",
  burgundy: "#6e2f33",
  yellow: "#d9b93f",
};

export const revalidate = 300;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const page = await getVariantPage(slug);
  return {
    title: page.variant ? page.variant.display_name : "Товар не найден",
    description: page.price?.min_price
      ? `Цены на «${page.variant?.display_name}» в магазинах Узбекистана: от ${formatPrice(page.price.min_price)} в ${page.price.store_count} магазинах.`
      : undefined,
  };
}

export default async function ProductPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const page = await getVariantPage(slug);
  if (!page.variant) notFound();

  const v = page.variant;
  const pr = page.price;

  const newest = page.offers.reduce<string | null>(
    (m, o) => (m == null || o.last_seen > m ? o.last_seen : m),
    null
  );
  const stale = newest != null && Date.now() - new Date(newest).getTime() > 24 * 3600_000;

  const cheapestInStock = page.offers.find((o) => o.availability === "IN_STOCK");
  const cheapestUnknown = page.offers.find((o) => o.availability === "UNKNOWN");

  return (
    <main>
      <div className="page">
        <div className="breadcrumbs">
          <a href="/">Главная</a>
          {" · "}
          <a href={`/c/${v.category}`}>{v.category === "smartphones" ? "Смартфоны" : v.category}</a>
          {" · "}
          <a href={`/c/${v.category}/${v.brand}`}>{v.brand}</a>
          {" · "}
          <span>{v.color ? colorRu(v.color) : "—"}</span>
        </div>

        {stale && (
          <div className="banner">
            Цены проверены {timeAgoRu(newest)} — магазины могли успеть их
            изменить. Мы показываем только то, что видели сами.
          </div>
        )}

        <section className="product">
          <h1>{v.display_name}</h1>
          <div className="subline">
            {v.ram_gb != null && <b>{v.ram_gb} ГБ ОЗУ</b>}
            {" · "}
            <b>{v.storage_gb} ГБ</b>
            {" · "}
            {v.sim_kind === "dual" ? "2 SIM / eSIM" : "только eSIM"}
          </div>

          <div className="headline">
            <div>
              <div className="from">
                от {pr ? pluralRu(pr.store_count, "магазина", "магазинов", "магазинов") : ""}{" "}
                {pr && pr.store_count > 0 ? "· дешевле всего в" : ""}
              </div>
              <div className="big">{formatPrice(pr?.min_price ?? null)}</div>
            </div>
            {pr?.min_offer_name && (
              <div className="provenance">
                Цена принадлежит конкретному предложению:{" "}
                <span className="q">
                  «{pr.min_offer_name}»{pr.min_store_name ? ` — ${pr.min_store_name}` : ""}
                </span>
                {pr.min_offer_url && (
                  <>
                    {" "}
                    <a href={`/api/out/${pr.min_offer_id ?? ""}`} style={{ textDecoration: "underline" }}>
                      проверить в магазине
                    </a>
                  </>
                )}
              </div>
            )}
          </div>

          {page.siblings.length > 1 && (
            <div className="sibling-picker">
              <h3>Другие цвета этой модели</h3>
              <div className="siblings">
                {page.siblings.map((sib) => {
                  const cur = sib.id === v.id;
                  const delta =
                    pr?.min_price != null && sib.min_price != null
                      ? sib.min_price - pr.min_price
                      : null;
                  return (
                    <a
                      key={sib.id}
                      className={`sib${cur ? " cur" : ""}`}
                      href={cur ? undefined : `/p/${sib.slug}`}
                      aria-current={cur ? "page" : undefined}
                    >
                      <span
                        className="swatch"
                        style={{ background: SWATCH_HEX[sib.color] ?? "#ccc" }}
                      />
                      {colorRu(sib.color)}
                      {sib.in_stock_offer_count > 0 ? (
                        <>
                          <span className="sib-price">{formatPrice(sib.min_price)}</span>
                          {delta != null && !cur && (
                            <span className={`sib-delta ${delta < 0 ? "delta-down" : "delta-up"}`}>
                              {delta < 0 ? "−" : "+"}
                              {formatPrice(Math.abs(delta))}
                            </span>
                          )}
                        </>
                      ) : (
                        <span className="sib-soldout">нет в продаже</span>
                      )}
                    </a>
                  );
                })}
              </div>
            </div>
          )}
        </section>

        <section className="compare">
          <div className="compare-head">
            <span>Магазин</span>
            <span>Цена от</span>
            <span>Диапазон предложений</span>
            <span>Наличие и проверка</span>
          </div>

          {page.stores.length === 0 && (
            <div className="empty" style={{ border: "none" }}>
              Ни одно предложение по этой модели пока не найдено. Загляните позже —
              каталог обновляется автоматически.
            </div>
          )}

          {page.stores.map((s) => {
            const inStockCount = s.in_stock;
            const unkCount = s.offers - s.in_stock;
            const hasStock = inStockCount > 0;
            const storeOffers = page.offers.filter(
              (o) => o.store_slug === s.store_slug
            );
            return (
              <details className="store-row" key={s.store_slug} open={false}>
                <summary>
                  <span className="store-cell-store">
                    <span className="store-badge">{s.store_slug}</span>
                    {s.store_name}
                  </span>
                  <span className="store-cell-price">{formatPrice(s.min_p)}</span>
                  <span className="store-cell-range">
                    {s.min_p != null && s.max_p != null && s.max_p > s.min_p
                      ? `${formatPrice(s.min_p)} — ${formatPrice(s.max_p)}`
                      : s.median_p != null
                        ? `медиана ${formatPrice(s.median_p)}`
                        : "—"}
                  </span>
                  <span className="store-cell-avail">
                    {hasStock ? (
                      <span className="avail in-stock">в наличии</span>
                    ) : unkCount > 0 ? (
                      <span className="avail unknown">наличие не указано</span>
                    ) : (
                      <span className="avail out-of-stock">нет в наличии</span>
                    )}
                    <span className="seen">
                      {pluralRu(s.offers, "предложение", "предложения", "предложений")}
                      {" · "}
                      {s.last_seen ? `проверено ${timeAgoRu(s.last_seen)}` : ""}
                    </span>
                  </span>
                </summary>
                <div className="offers">
                  {storeOffers.map((o) => {
                    const av = availabilityRu(o.availability);
                    return (
                      <div className="offer" key={o.id}>
                        <span className="o-name">
                          {o.name_raw}
                          <span className="avail" style={{ marginLeft: 8, ...(av.cls === "in-stock" ? {} : {}) }}>
                            {av.label}
                          </span>
                        </span>
                        <span className="o-price">{formatPrice(o.price)}</span>
                        {o.url && (
                          <a className="o-go" href={`/api/out/${o.id}`} rel="nofollow noopener">
                            В магазин →
                          </a>
                        )}
                      </div>
                    );
                  })}
                </div>
              </details>
            );
          })}
        </section>

        <p style={{ color: "var(--muted-2)", fontSize: 13, paddingBottom: 40 }}>
          {cheapestInStock ? (
            <>
              Дешевле всего — {cheapestInStock.store_name}: «
              {cheapestInStock.name_raw}» за {formatPrice(cheapestInStock.price)}.
            </>
          ) : cheapestUnknown ? (
            <>
              Самая низкая цена — {cheapestUnknown.store_name}: «
              {cheapestUnknown.name_raw}» за {formatPrice(cheapestUnknown.price)}.
              Магазин не указывает наличие.
            </>
          ) : (
            "Предложений в наличии нет."
          )}
        </p>
      </div>
    </main>
  );
}