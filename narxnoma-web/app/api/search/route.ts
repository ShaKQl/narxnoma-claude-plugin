import { NextRequest, NextResponse } from "next/server";
import { parseSearchParams } from "@/lib/searchParams";
import { searchVariants } from "@/lib/queries";

export const dynamic = "force-dynamic";

/**
 * /api/search — JSON twin of the SSR search page. Facet toggles fetch this
 * instead of navigating, so filtering is instant while the URL stays
 * shareable. Same parse + same query as the page: no drift possible.
 */
export async function GET(req: NextRequest) {
  const sp = Object.fromEntries(req.nextUrl.searchParams.entries());
  const p = parseSearchParams(sp);
  try {
    const res = await searchVariants({
      qNorm: p.qNorm,
      qTokens: p.qTokens,
      brands: p.brands,
      colors: p.colors,
      rams: p.rams,
      priceLo: p.priceLo,
      priceHi: p.priceHi,
      multiStore: p.multiStore,
      category: p.category,
      priced: p.priced,
      sort: p.sort,
      page: p.page,
    });
    return NextResponse.json(res);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "search failed" },
      { status: 500 }
    );
  }
}