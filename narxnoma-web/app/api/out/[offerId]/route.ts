import { NextRequest, NextResponse } from "next/server";
import { ensureWebSchema } from "@/lib/db";
import { getOfferForOut, recordOutbound } from "@/lib/queries";

export const dynamic = "force-dynamic";

/**
 * /api/out/[offerId] — 302 to the retailer listing, logging the click.
 * This is the honest link layer: the redirect target is the exact URL the
 * crawler saw, never a search page.
 */
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ offerId: string }> }
) {
  const { offerId } = await params;
  const offer = await getOfferForOut(offerId);
  if (!offer?.url) {
    return NextResponse.json({ error: "offer not found" }, { status: 404 });
  }
  // uzum: strip ?skuId= (see lib note / parser docstring). uzum's auth
  // redirect chokes on the raw nested query and answers with conflict JSON.
  let target = offer.url;
  if (target.startsWith("https://uzum.uz/")) {
    target = target.split("?")[0];
  }
  try {
    await ensureWebSchema();
    await recordOutbound(
      offerId,
      offer.variant_id,
      offer.store_id,
      req.headers.get("referer")
    );
  } catch {
    // A logging failure must never break the redirect.
  }
  return NextResponse.redirect(target, 302);
}