import { NextRequest, NextResponse } from "next/server";

// Ensure a lang cookie exists so the first render (and every request) has a
// locale. No URL prefix: the site is served at stable paths; language is a
// cookie preference (sitemap/hreflang stay simple).
export function middleware(req: NextRequest) {
  const hasLang = req.cookies.has("lang");
  const res = NextResponse.next();
  if (!hasLang) {
    res.cookies.set("lang", "ru", { path: "/", maxAge: 60 * 60 * 24 * 365 });
  }
  return res;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api|sitemap.xml|robots.txt).*)"],
};