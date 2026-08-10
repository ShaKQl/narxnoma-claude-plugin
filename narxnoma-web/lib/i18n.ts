// RU (source of truth) + UZ (Latin) UI dictionaries. Data-driven strings
// (retailer names, verbatim product titles) are never translated here.

export type Lang = "ru" | "uz";

const DICT: Record<string, { ru: string; uz: string }> = {
  "nav.search": { ru: "Поиск", uz: "Qidiruv" },
  "nav.catalog": { ru: "Каталог", uz: "Katalog" },
  "nav.stores": { ru: "Магазины", uz: "Do'konlar" },
  "nav.about": { ru: "О проекте", uz: "Loyiha haqida" },
  "hero.title": {
    ru: "Сравните цены на технику и электронику в {n} магазинах Узбекистана",
    uz: "O'zbekistonning {n} do'konida texnika narxlarini taqqoslang",
  },
  "hero.sub": {
    ru: "Смартфоны, телевизоры, ноутбуки и бытовая техника — введите название и мы покажем, кто продаёт дешевле. Рядом с каждой ценой — формулировка самого магазина, чтобы вы могли проверить совпадение.",
    uz: "Smartfonlar, televizorlar, noutbuklar va maishiy texnika — nomini kiriting, biz uni kim arzonroq sotayotganini ko'rsatamiz. Har bir narx yonida do'konning o'z yozuvi — siz mosligini tekshirishingiz mumkin.",
  },
  "home.categories": { ru: "Категории", uz: "Kategoriyalar" },
  "home.popular": { ru: "Популярное в каждой категории", uz: "Har bir kategoriyada mashhurlar" },
  "home.more": { ru: "все категории", uz: "barcha kategoriyalar" },
  "home.viewCategory": { ru: "Вся категория →", uz: "Butun kategoriya →" },
  "catalog.title": { ru: "Каталог", uz: "Katalog" },
  "catalog.sub": {
    ru: "Выберите категорию — в каждой мы сравниваем цены в 7 магазинах Узбекистана.",
    uz: "Kategoriyani tanlang — har birida biz O'zbekistondagi 7 do'kon narxlarini solishtiramiz.",
  },
  "cat.all": { ru: "Все категории", uz: "Barcha kategoriyalar" },
  "search.ph": { ru: "Название товара", uz: "Mahsulot nomi" },
  "search.go": { ru: "Найти", uz: "Topish" },
  "stat.stores": { ru: "магазинов", uz: "do'kon" },
  "stat.offers": { ru: "предложений", uz: "taklif" },
  "stat.models": { ru: "моделей", uz: "model" },
  "stat.updated": { ru: "обновлено из базы", uz: "bazadan yangilandi" },
  "home.mostStores": { ru: "Где больше всего магазинов", uz: "Eng ko'p do'konlar qayerda" },
  "home.brands": { ru: "Каталог по брендам", uz: "Brendlar katalogi" },
  "facet.onlyComparable": { ru: "Только сравнимые", uz: "Faqat taqqoslanadiganlar" },
  "facet.multi": { ru: "2+ магазина", uz: "2+ do'kon" },
  "facet.brand": { ru: "Бренд", uz: "Brend" },
  "facet.color": { ru: "Цвет", uz: "Rang" },
  "facet.ram": { ru: "Оперативная память", uz: "Operativ xotira" },
  "facet.price": { ru: "Цена", uz: "Narx" },
  "facet.none": { ru: "не указана", uz: "ko'rsatilmagan" },
  "facet.filters": { ru: "Фильтры", uz: "Filterlar" },
  "sort.relevance": { ru: "по релевантности", uz: "moslik bo'yicha" },
  "sort.price_asc": { ru: "сначала дешевле", uz: "avval arzonlari" },
  "sort.price_desc": { ru: "сначала дороже", uz: "avval qimmatlari" },
  "sort.stores": { ru: "по числу магазинов", uz: "do'konlar soni bo'yicha" },
  "res.updating": { ru: "обновляем…", uz: "yangilanmoqda…" },
  "res.empty": {
    ru: "По запросу «{q}» ничего не найдено.",
    uz: "«{q}» so'rovi bo'yicha hech narsa topilmadi.",
  },
  "res.emptyHint": {
    ru: "Попробуйте другое написание — например, «iPhone 17» или «Redmi Note 15».",
    uz: "Boshqa yozuvni sinab ko'ring — masalan, «iPhone 17» yoki «Redmi Note 15».",
  },
  "p.otherColors": { ru: "Другие цвета этой модели", uz: "Ushbu modelning boshqa ranglari" },
  "p.outOfStock": { ru: "нет в продаже", uz: "sotuvda yo'q" },
  "p.min": { ru: "от", uz: "dan" },
  "p.median": { ru: "медиана", uz: "mediana" },
  "p.range": { ru: "диапазон предложений", uz: "takliflar oralig'i" },
  "p.avail": { ru: "наличие и проверка", uz: "mavjudligi va tekshiruv" },
  "p.inStock": { ru: "в наличии", uz: "bor" },
  "p.outStock": { ru: "нет в наличии", uz: "yo'q" },
  "p.unknown": { ru: "наличие не указано", uz: "mavjudligi ko'rsatilmagan" },
  "p.checkedAgo": { ru: "проверено {t} назад", uz: "{t} oldin tekshirildi" },
  "p.offersCount": { ru: "предложение", uz: "taklif" },
  "p.cheapest": {
    ru: "Дешевле всего — {store}: «{name}» за {price}.",
    uz: "Eng arzoni — {store}: «{name}» {price}.",
  },
  "p.checkInStore": { ru: "проверить в магазине", uz: "do'konda tekshirish" },
  "p.stale": {
    ru: "Цены проверены {t} — магазины могли успеть их изменить. Мы показываем только то, что видели сами.",
    uz: "Narxlar {t} tekshirilgan — do'konlar ularni o'zgartirgan bo'lishi mumkin. Biz faqat o'zimiz ko'rgan narsani ko'rsatamiz.",
  },
  "footer.line": {
    ru: "Нархнома — агрегатор цен. Мы ничего не продаём: цена каждого предложения ведёт на страницу магазина, где вы можете проверить её сами.",
    uz: "Narxnoma — narxlar agregatori. Biz hech narsa sotmaymiz: har bir taklif narxi do'kon sahifasiga olib boradi, u yerda o'zingiz tekshirishingiz mumkin.",
  },
  "footer.sources": {
    ru: "Источники: {stores} · данные обновляются автоматически",
    uz: "Manbalar: {stores} · ma'lumotlar avtomatik yangilanadi",
  },
  "stores.title": { ru: "Магазины", uz: "Do'konlar" },
  "stores.health": { ru: "Здоровье источников", uz: "Manbalar holati" },
  "stores.ok": { ru: "здоров", uz: "sog'lom" },
  "stores.quiet": { ru: "тихо", uz: "sokin" },
  "stores.error": { ru: "ошибка", uz: "xato" },
  "about.title": { ru: "О проекте", uz: "Loyiha haqida" },
  "cat.smartphones": { ru: "Смартфоны", uz: "Smartfonlar" },
  "cat.televisions": { ru: "Телевизоры", uz: "Televizorlar" },
  "cat.laptops": { ru: "Ноутбуки", uz: "Noutbuklar" },
  "cat.acs": { ru: "Кондиционеры", uz: "Konditsionerlar" },
  "cat.fridges": { ru: "Холодильники", uz: "Sovutgichlar" },
  "cat.washers": { ru: "Стиральные машины", uz: "Kir yuvish mashinalari" },
  "cat.ovens": { ru: "Духовые шкафы", uz: "Duxovkalar" },
};

export function langFromCookie(value?: string | null): Lang {
  // value is the cookie VALUE ("uz"/"ru"), not a cookie header. (Bug
  // 2026-08-10: this previously parsed it as "lang=uz; …" and so never
  // matched, i.e. the UZ switch silently did nothing.)
  return value === "uz" ? "uz" : "ru";
}

export function t(lang: Lang, key: string, vars?: Record<string, string | number>): string {
  const row = DICT[key];
  if (!row) return key;
  let s = row[lang];
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      s = s.replaceAll(`{${k}}`, String(v));
    }
  }
  return s;
}

/** Pluralisation. RU: 1/2-4/5+; UZ: invariant "N ta" (count + fixed word). */
export function plural(
  lang: Lang,
  n: number,
  uz: string,
  ruOne: string,
  ruFew: string,
  ruMany: string
): string {
  if (lang === "uz") return `${n} ${uz}`; // Uzbek is count-invariant
  const abs = Math.abs(n) % 100;
  const mod10 = abs % 10;
  if (abs > 10 && abs < 20) return `${n} ${ruMany}`;
  if (mod10 === 1) return `${n} ${ruOne}`;
  if (mod10 >= 2 && mod10 <= 4) return `${n} ${ruFew}`;
  return `${n} ${ruMany}`;
}

/** Currency word + thousands grouping. */
export function price(lang: Lang, sum: number | null | undefined): string {
  if (sum == null) return lang === "uz" ? "so'm" : "сум";
  const grouped = Math.round(sum)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, "\u00A0");
  return `${grouped}\u00A0${lang === "uz" ? "so'm" : "сум"}`;
}

/** Relative time. */
export function timeAgo(lang: Lang, then: string | Date): string {
  const d = new Date(then);
  const s = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (s < 60) return lang === "uz" ? "hozirgina" : "только что";
  const m = Math.floor(s / 60);
  if (m < 60) return lang === "uz" ? `${m} daqiqa oldin` : `${m} мин назад`;
  const h = Math.floor(m / 60);
  if (h < 24) return lang === "uz" ? `${h} soat oldin` : `${h} ч назад`;
  const days = Math.floor(h / 24);
  if (days === 1) return lang === "uz" ? "kecha" : "вчера";
  return lang === "uz" ? `${days} kun oldin` : `${days} дн назад`;
}