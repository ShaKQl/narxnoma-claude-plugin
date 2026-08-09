// Canonical colour keys (matching/colors.py) -> Russian display names.
// These are the adjective forms the crawler itself puts into display_name,
// so the UI never has to translate ad-hoc.
export const COLOR_RU: Record<string, string> = {
  black: "Черный",
  white: "Белый",
  silver: "Серебристый",
  gray: "Серый",
  gold: "Золотой",
  blue: "Синий",
  red: "Красный",
  brown: "Коричневый",
  green: "Зеленый",
  purple: "Фиолетовый",
  orange: "Оранжевый",
  pink: "Розовый",
  beige: "Бежевый",
  burgundy: "Бордовый",
  yellow: "Желтый",
};

export const COLORS = Object.keys(COLOR_RU);

export function colorRu(key: string | null | undefined): string {
  if (!key) return "—";
  return COLOR_RU[key] ?? key;
}