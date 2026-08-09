import { NextRequest, NextResponse } from "next/server";
import { getSearchSuggestions } from "@/lib/queries";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const q = req.nextUrl.searchParams.get("q")?.trim() ?? "";
  if (!q || q.length < 2) {
    return NextResponse.json({ variants: [], brands: [] });
  }
  try {
    const r = await getSearchSuggestions(q);
    return NextResponse.json(r);
  } catch {
    return NextResponse.json({ variants: [], brands: [] });
  }
}