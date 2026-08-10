import type { Metadata } from "next";
import { cookies } from "next/headers";
import { JetBrains_Mono, Manrope } from "next/font/google";
import { LangProvider } from "@/components/LangProvider";
import LangSwitcher from "@/components/LangSwitcher";
import { langFromCookie, t } from "@/lib/i18n";
import "./globals.css";

// Design token "Archivo" has no Cyrillic subset; Manrope is the closest
// geometric grotesque with full Cyrillic coverage (spec §7: RU + UZ UI).
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

const STORES = "Uzum, Alif Shop, BeeMarket, Idea, Mediapark, Olcha, Texnomart";

export const metadata: Metadata = {
  title: {
    default: "Нархнома — сравнение цен на технику в Узбекистане",
    template: "%s · Нархнома",
  },
  description:
    "Введите название техники — смартфона, телевизора, ноутбука — и сравните цены Uzum, Alif Shop, BeeMarket, Idea, Mediapark, Olcha и Texnomart. Рядом с каждой ценой — точная формулировка магазина, чтобы вы сами могли проверить совпадение.",
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const store = await cookies();
  const lang = langFromCookie(store.get("lang")?.value);

  return (
    <html lang={lang} className={`${archivo.variable} ${mono.variable}`}>
      <body>
        <LangProvider lang={lang}>
          <header className="topnav">
            <div className="topnav-inner">
              <a className="brand" href="/">
                <span className="brand-mark">Н</span>
                <span className="brand-name">
                  Нархнома<span className="brand-dot">.</span>
                </span>
              </a>
              <nav className="topnav-links">
                <a href="/search">{t(lang, "nav.search")}</a>
                <a href="/catalog">{t(lang, "nav.catalog")}</a>
                <a href="/stores">{t(lang, "nav.stores")}</a>
                <a href="/about">{t(lang, "nav.about")}</a>
                <LangSwitcher />
              </nav>
            </div>
          </header>
          {children}
          <footer className="footer">
            <div className="page">
              <p>{t(lang, "footer.line")}</p>
              <p className="footer-muted">
                {t(lang, "footer.sources", { stores: STORES })}
              </p>
            </div>
          </footer>
        </LangProvider>
      </body>
    </html>
  );
}