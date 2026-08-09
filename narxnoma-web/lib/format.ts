// RU formatting helpers: prices, plurals, relative time. Every number rendered
// on a page goes through here so JetBrains Mono + narrow-NBSP grouping is
// applied in exactly one place.

const NBSP = "\u202F"; // narrow no-break space for digit grouping

export function formatPrice(sum: number | null | undefined): string {
  if (sum == null) return "—";
  const digits = Math.abs(sum)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  return `${digits}\u00A0сум`;
}

/** Pluralisation: pluralRu(3, "магазин", "магазина", "магазинов") -> "3 магазина" */
export function pluralRu(
  n: number,
  one: string,
  few: string,
  many: string
): string {
  const abs = Math.abs(n) % 100;
  const d = abs % 10;
  if (abs >= 11 && abs <= 19) return `${n}\u00A0${many}`;
  if (d === 1) return `${n}\u00A0${one}`;
  if (d >= 2 && d <= 4) return `${n}\u00A0${few}`;
  return `${n}\u00A0${many}`;
}

export function timeAgoRu(ts: string | Date | null | undefined): string {
  if (!ts) return "никогда";
  const then = new Date(ts).getTime();
  const diffMs = Date.now() - then;
  if (diffMs < 0) return "только что";
  const min = Math.floor(diffMs / 60_000);
  if (min < 1) return "только что";
  if (min < 60) return pluralRu(min, "мин назад", "мин назад", "мин назад");
  const h = Math.floor(min / 60);
  if (h < 24) return pluralRu(h, "час назад", "часа назад", "часов назад");
  const d = Math.floor(h / 24);
  if (d === 1) return "вчера";
  return pluralRu(d, "день назад", "дня назад", "дней назад");
}

export function formatDateRu(ts: string | Date | null | undefined): string {
  if (!ts) return "—";
  return new Date(ts).toLocaleString("ru-RU", {
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Availability strings used by the crawler (offer.availability). */
export type Availability = "IN_STOCK" | "OUT_OF_STOCK" | "UNKNOWN";

export function availabilityRu(a: string | null | undefined): {
  label: string;
  cls: string;
} {
  switch (a) {
    case "IN_STOCK":
      return { label: "в наличии", cls: "in-stock" };
    case "OUT_OF_STOCK":
      return { label: "нет в наличии", cls: "out-of-stock" };
    case "UNKNOWN":
      return { label: "наличие не указано", cls: "unknown" };
    default:
      return { label: "—", cls: "unknown" };
  }
}