import type { Metadata } from "next";
import { pluralRu, timeAgoRu } from "@/lib/format";
import { getStoresHealth } from "@/lib/queries";

export const revalidate = 300;

export const metadata: Metadata = { title: "Магазины" };

export default async function StoresPage() {
  const stores = await getStoresHealth();
  return (
    <main>
      <div className="page">
        <section className="sec">
          <h1>Магазины</h1>
          <p className="sub">
            Состояние каждого источника: когда проходила последняя проверка и
            сколько предложений мы видим. Если магазин давно не отвечал — мы
            честно показываем это, а не продолжаем выдавать устаревшие цены.
          </p>
          {stores.map((s) => {
            const fresh = s.fresh_24h > 0;
            const lastTry = s.last_try ? new Date(s.last_try).getTime() : null;
            const daysSinceTry =
              lastTry != null
                ? Math.floor((Date.now() - lastTry) / 86_400_000)
                : null;
            let health: { cls: string; label: string } = { cls: "muted", label: "нет данных" };
            if (s.last_error != null) health = { cls: "bad", label: "последняя проверка с ошибкой" };
            else if (fresh) health = { cls: "ok", label: "проверено за последние 24 ч" };
            else if (daysSinceTry != null && daysSinceTry <= 2)
              health = { cls: "warn", label: "данные старше суток" };
            else if (daysSinceTry != null)
              health = { cls: "bad", label: `не проверялся ${daysSinceTry} дн` };
            return (
              <div className="store-card" key={s.slug}>
                <div>
                  <div className="s-name">
                    <span className={`health ${health.cls}`}>{health.label}</span>
                    {s.name}
                  </div>
                  <div className="s-meta" style={{ marginTop: 6 }}>
                    {pluralRu(s.offers, "предложение", "предложения", "предложений")}
                    {" · свежих за 24 ч: "}
                    {s.fresh_24h}
                    {" · последняя проверка: "}
                    {s.last_ok ? timeAgoRu(s.last_ok) : "никогда"}
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
                    Сайт магазина ↗
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