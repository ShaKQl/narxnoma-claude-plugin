import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { colorRu } from "@/lib/colors";
import { langFromCookie, plural, price, t, timeAgo } from "@/lib/i18n";
import { getVariantPage } from "@/lib/queries";
import SafeImg from "@/components/SafeImg";

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

export const dynamic = "force-dynamic";

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
      ? `Цены на «${page.variant?.display_name}» в магазинах Узбекистана.`
      : undefined,
  };
}

export default async function ProductPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const lang = langFromCookie((await cookies()).get("lang")?.value);
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

  const avail = (a: string) => {
    if (a === "IN_STOCK") return { label: t(lang, "p.inStock"), cls: "in-stock" };
    if (a === "OUT_OF_STOCK") return { label: t(lang, "p.outStock"), cls: "out-of-stock" };
    return { label: t(lang, "p.unknown"), cls: "unknown" };
  };
  const catLabel = (c: string) =>
    c === "smartphones" ? t(lang, "cat.smartphones") : c;

  return (
    <main>
      <div className="page">
        <div className="breadcrumbs">
          <a href="/">{lang === "uz" ? "Bosh sahifa" : "Главная"}</a>
          {" · "}
          <a href={`/c/${v.category}`}>{catLabel(v.category)}</a>
          {" · "}
          <a href={`/c/${v.category}/${v.brand}`}>{v.brand}</a>
          {/* Colour is identity only for phones. Outside them it is NULL, and
              the old "—" placeholder left a dangling "· —" on every
              television, fridge and laptop breadcrumb. */}
          {v.color && (
            <>
              {" · "}
              <span>{colorRu(v.color)}</span>
            </>
          )}
        </div>

        {stale &&
          (() => {
            const ago = timeAgo(lang, newest!);
            return <div className="banner">{t(lang, "p.stale", { t: ago })}</div>;
          })()}

        <section className="product">
          {pr?.hero_image_url && (
            <SafeImg
              className="product-hero"
              src={pr.hero_image_url}
              alt={v.display_name}
            />
          )}
          <h1>{v.display_name}</h1>
          {/* Built by joining only the specs this product actually HAS.
              Outside phones, storage/colour/SIM are NULL by design, and the
              old fixed layout rendered a bare " · ГБ" for every television. */}
          <div className="subline">
            {[
              v.ram_gb != null ? `${v.ram_gb} ГБ ОЗУ` : null,
              v.storage_gb != null ? `${v.storage_gb} ГБ` : null,
              v.category === "smartphones"
                ? v.sim_kind === "dual"
                  ? "2 SIM / eSIM"
                  : v.sim_kind === "esim_only"
                    ? "eSIM"
                    : null
                : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </div>

          <div className="headline">
            <div>
              <div className="from">
                {lang === "uz" ? "dan" : "от"}{" "}
                {pr ? plural(lang, pr.store_count, "do'kon", "магазина", "магазинов", "магазинов") : ""}{" "}
                {pr && pr.store_count > 0
                  ? lang === "uz"
                    ? "· eng arzoni"
                    : "· дешевле всего в"
                  : ""}
              </div>
              <div className="big">{price(lang, pr?.min_price ?? null)}</div>
            </div>
            {pr?.min_offer_name && (
              <div className="provenance">
                {lang === "uz"
                  ? "Narx aniq taklifga tegishli:"
                  : "Цена принадлежит конкретному предложению:"}{" "}
                <span className="q">
                  «{pr.min_offer_name}»{pr.min_store_name ? ` — ${pr.min_store_name}` : ""}
                </span>
                {pr.min_offer_url && (
                  <>
                    {" "}
                    <a href={`/api/out/${pr.min_offer_id ?? ""}`} style={{ textDecoration: "underline" }}>
                      {t(lang, "p.checkInStore")}
                    </a>
                  </>
                )}
              </div>
            )}
          </div>

          {page.siblings.length > 1 && (
            <div className="sibling-picker">
              <h3>{t(lang, "p.otherColors")}</h3>
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
                          <span className="sib-price">{price(lang, sib.min_price)}</span>
                          {delta != null && !cur && (
                            <span className={`sib-delta ${delta < 0 ? "delta-down" : "delta-up"}`}>
                              {delta < 0 ? "−" : "+"}
                              {price(lang, Math.abs(delta))}
                            </span>
                          )}
                        </>
                      ) : (
                        <span className="sib-soldout">{t(lang, "p.outOfStock")}</span>
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
            <span>{lang === "uz" ? "Do'kon" : "Магазин"}</span>
            <span>{lang === "uz" ? "Narx dan" : "Цена от"}</span>
            <span>{lang === "uz" ? "Takliflar oralig'i" : "Диапазон предложений"}</span>
            <span>{lang === "uz" ? "Mavjudligi" : "Наличие и проверка"}</span>
          </div>

          {page.stores.length === 0 && (
            <div className="empty" style={{ border: "none" }}>
              {lang === "uz"
                ? "Bu model bo'yicha hozircha taklif yo'q. Keyinroq qarang — katalog avtomatik yangilanadi."
                : "Ни одно предложение по этой модели пока не найдено. Загляните позже — каталог обновляется автоматически."}
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
                  <span className="store-cell-price">{price(lang, s.min_p)}</span>
                  <span className="store-cell-range">
                    {s.min_p != null && s.max_p != null && s.max_p > s.min_p
                      ? `${price(lang, s.min_p)} — ${price(lang, s.max_p)}`
                      : s.median_p != null
                        ? `${lang === "uz" ? "mediana" : "медиана"} ${price(lang, s.median_p)}`
                        : "—"}
                  </span>
                  <span className="store-cell-avail">
                    {hasStock ? (
                      <span className="avail in-stock">{t(lang, "p.inStock")}</span>
                    ) : unkCount > 0 ? (
                      <span className="avail unknown">{t(lang, "p.unknown")}</span>
                    ) : (
                      <span className="avail out-of-stock">{t(lang, "p.outStock")}</span>
                    )}
                    <span className="seen">
                      {plural(lang, s.offers, "taklif", "предложение", "предложения", "предложений")}
                      {" · "}
                      {s.last_seen
                        ? `${lang === "uz" ? "oldin tekshirildi " : "проверено "} ${timeAgo(lang, s.last_seen)}`
                        : ""}
                    </span>
                  </span>
                </summary>
                <div className="offers">
                  {storeOffers.map((o) => {
                    const av = avail(o.availability);
                    return (
                      <div className="offer" key={o.id}>
                        <span className="o-name">
                          {o.image_url && (
                            <SafeImg
                              className="o-thumb"
                              src={o.image_url}
                              thumb
                            />
                          )}
                          {o.name_raw}
                          <span className={`avail ${av.cls}`} style={{ marginLeft: 8 }}>
                            {av.label}
                          </span>
                        </span>
                        <span className="o-price">{price(lang, o.price)}</span>
                        {o.url && (
                          <a className="o-go" href={`/api/out/${o.id}`} rel="nofollow noopener">
                            {lang === "uz" ? "Do'konga →" : "В магазин →"}
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
              {lang === "uz"
                ? `Eng arzoni — ${cheapestInStock.store_name}: «${cheapestInStock.name_raw}» ${price(lang, cheapestInStock.price)}.`
                : `Дешевле всего — ${cheapestInStock.store_name}: «${cheapestInStock.name_raw}» за ${price(lang, cheapestInStock.price)}.`}
            </>
          ) : cheapestUnknown ? (
            <>
              {lang === "uz"
                ? `Eng past narx — ${cheapestUnknown.store_name}: «${cheapestUnknown.name_raw}» ${price(lang, cheapestUnknown.price)}. Do'kon mavjudligini ko'rsatmaydi.`
                : `Самая низкая цена — ${cheapestUnknown.store_name}: «${cheapestUnknown.name_raw}» за ${price(lang, cheapestUnknown.price)}. Магазин не указывает наличие.`}
            </>
          ) : (
            (lang === "uz" ? "Sotuvda taklif yo'q." : "Предложений в наличии нет.")
          )}
        </p>
      </div>
    </main>
  );
}