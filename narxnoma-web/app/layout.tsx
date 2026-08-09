import type { Metadata } from "next";
import { JetBrains_Mono, Manrope } from "next/font/google";
import "./globals.css";

// Design token "Archivo" has no Cyrillic subset; Manrope is the closest
// geometric grotesque with full Cyrillic coverage (spec §7: Russian UI).
const archivo = Manrope({
  subsets: ["latin", "cyrillic"],
  variable: "--font-archivo",
  display: "swap",
});
const mono = JetBrains_Mono({
  subsets: ["latin", "cyrillic"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Нархнома — сравнение цен на смартфоны в Узбекистане",
    template: "%s · Нархнома",
  },
  description:
    "Введите название смартфона и сравните цены Uzum, Alif Shop, BeeMarket, Idea, Mediapark, Olcha и Texnomart. Рядом с каждой ценой — точная формулировка магазина, чтобы вы сами могли проверить совпадение.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru" className={`${archivo.variable} ${mono.variable}`}>
      <body>
        <header className="topnav">
          <div className="topnav-inner">
            <a className="brand" href="/">
              <span className="brand-mark">Н</span>
              <span className="brand-name">
                Нархнома<span className="brand-dot">.</span>
              </span>
            </a>
            <nav className="topnav-links">
              <a href="/search">Поиск</a>
              <a href="/c/smartphones">Каталог</a>
              <a href="/stores">Магазины</a>
              <a href="/about">О проекте</a>
            </nav>
          </div>
        </header>
        {children}
        <footer className="footer">
          <div className="page">
            <p>
              Нархнома — агрегатор цен. Мы ничего не продаём: цена каждого
              предложения ведёт на страницу магазина, где вы можете проверить её
              сами.
            </p>
            <p className="footer-muted">
              Источники: Uzum, Alif Shop, BeeMarket, Idea, Mediapark, Olcha,
              Texnomart · данные обновляются автоматически
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}