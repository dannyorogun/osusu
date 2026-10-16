import { NextResponse, type NextRequest } from "next/server";

import { REFRESH_COOKIE } from "@/lib/server/session";

/**
 * Optimistic route protection (UX only, NOT authorization): visitors
 * without a session cookie are sent to /login before any app page loads.
 * Every piece of private data is still authorized by Django on each API
 * request; the cookie's presence proves nothing by itself.
 */
export function proxy(request: NextRequest) {
  if (request.cookies.has(REFRESH_COOKIE)) return NextResponse.next();

  const login = new URL("/login", request.url);
  login.searchParams.set("next", request.nextUrl.pathname);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/circles/:path*",
    "/profile/:path*",
    "/payments/:path*",
    "/payouts/:path*",
    "/trust/:path*",
    "/assistant/:path*",
  ],
};
