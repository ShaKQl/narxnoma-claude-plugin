import { Pool } from "pg";

declare global {
  // eslint-disable-next-line no-var
  var __narxnomaPool: Pool | undefined;
}

// One pool per process; Next dev hot-reloads modules, so guard against leaks.
export const pool: Pool =
  global.__narxnomaPool ??
  new Pool({
    connectionString:
      process.env.DATABASE_URL ??
      "postgresql://narxnoma@127.0.0.1:55432/narxnoma",
    max: 10,
    connectionTimeoutMillis: 5000,
    statement_timeout: 10_000,
  });

if (process.env.NODE_ENV !== "production") global.__narxnomaPool = pool;

export async function query<T extends object>(
  text: string,
  params: unknown[] = []
): Promise<T[]> {
  const res = await pool.query(text, params);
  return res.rows as T[];
}

/** Idempotent schema bits the web owns (click log for /api/out). */
export async function ensureWebSchema(): Promise<void> {
  await query(`
    CREATE TABLE IF NOT EXISTS outbound_click (
      id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      offer_id    uuid NOT NULL,
      variant_id  uuid,
      store_id    uuid,
      referer     text,
      clicked_at  timestamptz NOT NULL DEFAULT now()
    )
  `);
}