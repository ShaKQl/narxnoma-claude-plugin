import type { Metadata } from "next";
import { cookies } from "next/headers";
import { langFromCookie, plural, timeAgo } from "@/lib/i18n";
import { getStoresHealth } from "@/lib/queries";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Магазины" };

export default async function StoresPage() {
  const lang = langFromCookie((await cookies()).get("lang")?.value);
  const stores = await getStoresHealth();
  const uz = lang === "uz";
  return (
    <main>
      <div className="page">
        <section className="sec">
          <h1>{uz ? "Do'konlar" : "Магазины"}</h1>
          <p className="sub">
            {uz
              ? "Har bir manba holati: oxirgi tekshiruv qachon o'tgan va qancha taklif ko'ramiz. Agar do'kon uzoq vaqt javob bermasa — biz buni halol ko'rsatamiz va eskirgan narxlarni chiqarmasak bo'lmaydi."
              : "Состояние каждого источника: когда проходила последняя проверка и сколько предложений мы видим. Если магазин давно не отвечал — мы честно показываем это, а не продолжаем выдавать устаревшие цены."}
          </p>
          {stores.map((s) => {
            const fresh = s.fresh_24h > 0;
            const lastTry = s.last_try ? new Date(s.last_try).getTime() : null;
            const daysSinceTry =
              lastTry != null
                ? Math.floor((Date.now() - lastTry) / 86_400_000)
                : null;
            let health: { cls: string; label: string } = {
              cls: "muted",
              label: uz ? "ma'lumot yo'q" : "нет данных",
            };
            if (s.last_error != null)
              health = {
                cls: "bad",
                label: uz ? "oxirgi tekshiruv xatolik bilan" : "последняя проверка с ошибкой",
              };
            else if (fresh)
              health = {
                cls: "ok",
                label: uz ? "oxirgi 24 soatda tekshirildi" : "проверено за последние 24 ч",
              };
            else if (daysSinceTry != null && daysSinceTry <= 2)
              health = { cls: "warn", label: uz ? "ma'lumot bir sutkadan eski" : "данные старше суток" };
            else if (daysSinceTry != null)
              health = {
                cls: "bad",
                label: uz ? `${daysSinceTry} kun tekshirilmagan` : `не проверялся ${daysSinceTry} дн`,
              };
            return (
              <div className="store-card" key={s.slug}>
                <div>
                  <div className="s-name">
                    <span className={`health ${health.cls}`}>{health.label}</span>
                    {s.name}
                  </div>
                  <div className="s-meta" style={{ marginTop: 6 }}>
                    {plural(lang, s.offers, "taklif", "предложение", "предложения", "предложений")}
                    {uz ? " · 24 soatda yangi: " : " · свежих за 24 ч: "}
                    {s.fresh_24h}
                    {uz ? " · oxirgi tekshiruv: " : " · последняя проверка: "}
                    {s.last_ok ? timeAgo(lang, s.last_ok) : uz ? "hech qachon" : "никогда"}
                  </div>
                </div>
                {s.website_url && (
                  <a
                    className="o-go"
                    href={s.website_url}
                    target="_blank"
                    rel="nofollow noopener noreferrer"
                    style={{
                      display: "inline-block",
                      background: "var(--ink)",
                      color: "var(--card)",
                      padding: "10px 16px",
                      fontWeight: 600,
                      fontSize: 14,
                    }}
                  >
                    {uz ? "Do'kon sayti ↗" : "Сайт магазина ↗"}
                  </a>
                )}
              </div>
            );
          })}
        </section>
      </div>
    </main>
  );
}