import { NextRequest, NextResponse } from "next/server";
import { revalidatePath } from "next/cache";

export const dynamic = "force-dynamic";

/**
 * /api/revalidate — called by the crawler after a cycle finishes.
 * POST with `secret` in the body (or ?secret=) matching REVALIDATE_SECRET.
 * Revalidates every cached page so ISR pages reflect the new data.
 */
export async function POST(req: NextRequest) {
  const secret = process.env.REVALIDATE_SECRET ?? "dev-secret-change-me";
  let body: Record<string, unknown> = {};
  try {
    body = await req.json();
  } catch {
    body = {};
  }
  const given =
    (body.secret as string | undefined) ??
    req.nextUrl.searchParams.get("secret") ??
    "";
  if (given !== secret) {
    return NextResponse.json({ error: "invalid secret" }, { status: 401 });
  }

  const paths = ["/", "/search", "/stores", "/c/smartphones"];
  for (const p of paths) revalidatePath(p);
  // Revalidate the search results page generically (path-less revalidate of
  // all dynamic segments would be ideal; per-path is deterministic).
  return NextResponse.json({ ok: true, revalidated: paths });
}