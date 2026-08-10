"use client";

import Link from "next/link";
import { colorRu } from "@/lib/colors";
import { price, plural } from "@/lib/i18n";
import { useLang } from "./LangProvider";
import type { VariantHit } from "@/lib/queries";

/**
 * Spec chips for one card.
 *
 * Phones carry a full signature — RAM, storage, colour, dual/eSIM — and every
 * field is identity. Nothing outside phones does: a television has no storage
 * and no SIM, and its colour is deliberately not part of its identity, so
 * those columns are NULL. Rendering the phone chips regardless printed an
 * empty "ГБ" and, because the SIM chip was a bare ternary with no null branch,
 * the words "eSIM" on a refrigerator.
 *
 * A chip is shown only where the value exists. Nothing is invented, and a
 * category with no structured spec simply shows none — the catalogue code in
 * the product name is what identifies it.
 */
function specChips(v: VariantHit, lang: string) {
  const chips: string[] = [];
  const ram = lang === "uz" ? "GB operativ" : "ГБ ОЗУ";
  const gb = lang === "uz" ? "GB" : "ГБ";

  if (v.ram_gb != null) chips.push(`${v.ram_gb} ${ram}`);
  if (v.storage_gb != null) chips.push(`${v.storage_gb} ${gb}`);
  if (v.color) chips.push(colorRu(v.color));
  if (v.sim_kind === "dual") chips.push("2 SIM");
  else if (v.sim_kind === "esim_only") chips.push("eSIM");

  return chips.map((c) => (
    <span className="spec" key={c}>
      {c}
    </span>
  ));
}

/**
 * Product image is hotlinked from the retailer's CDN — never stored locally
 * (storage would scale with catalogue size; hotlinks do not). no-referrer +
 * lazy keep retailer CDNs and the user's bandwidth happy. Broken images
 * collapse to the brand placeholder.
 */
export default function VariantCard({ v }: { v: VariantHit }) {
  const lang = useLang();
  const delta =
    v.median_price != null && v.min_price != null
      ? v.median_price - v.min_price
      : null;
  return (
    <Link href={`/p/${v.slug}`} className="card">
      <div className="card-top">
        <span className="card-brand">{v.brand}</span>
        {v.store_count >= 2 && (
          <span className="stores-n">
            {plural(lang, v.store_count, "do'kon", "магазин", "магазина", "магазинов")}
          </span>
        )}
      </div>
      {v.image_url ? (
        <div className="card-image">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={v.image_url}
            alt=""
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            onError={(e) => {
              (e.currentTarget.parentElement as HTMLElement).classList.add(
                "img-missing"
              );
              e.currentTarget.style.display = "none";
            }}
          />
        </div>
      ) : (
        <div className="card-image img-missing" aria-hidden="true">
          <span>{v.brand.charAt(0).toUpperCase()}</span>
        </div>
      )}
      <div className="card-name">{v.display_name}</div>
      <div className="specs">{specChips(v, lang)}</div>
      <div className="card-price-row">
        <span className="price">
          <span className="from">{lang === "uz" ? "dan " : "от "}</span>
          {price(lang, v.min_price)}
        </span>
        {delta != null && delta > 0 && (
          <span className="stores-n">
            {lang === "uz" ? "mediana" : "медиана"} <b>{price(lang, v.median_price)}</b>
          </span>
        )}
      </div>
    </Link>
  );
}