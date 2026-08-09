import Link from "next/link";
import { colorRu } from "@/lib/colors";
import { formatPrice, pluralRu } from "@/lib/format";
import type { VariantHit } from "@/lib/queries";

export default function VariantCard({ v }: { v: VariantHit }) {
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
            <b>{v.store_count}</b> {pluralRu(v.store_count, "магазин", "магазина", "магазинов")}
          </span>
        )}
      </div>
      <div className="card-name">{v.display_name}</div>
      <div className="specs">
        {v.ram_gb != null && <span className="spec">{v.ram_gb} ГБ ОЗУ</span>}
        <span className="spec">{v.storage_gb} ГБ</span>
        {v.color && <span className="spec">{colorRu(v.color)}</span>}
        {v.sim_kind === "dual" ? (
          <span className="spec">2 SIM</span>
        ) : (
          <span className="spec">eSIM</span>
        )}
      </div>
      <div className="card-price-row">
        <span className="price">
          <span className="from">от&nbsp;</span>
          {formatPrice(v.min_price)}
        </span>
        {delta != null && delta > 0 && (
          <span className="stores-n">
            медиана <b>{formatPrice(v.median_price)}</b>
          </span>
        )}
      </div>
    </Link>
  );
}