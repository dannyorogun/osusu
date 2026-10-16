import type { NextRequest } from "next/server";

import {
  REFRESH_COOKIE,
  clearRefreshCookie,
  isSameOrigin,
  json,
  postToDjango,
} from "@/lib/server/session";

/**
 * POST /api/session/logout -> revokes the refresh token in Django
 * (POST /api/auth/logout/, SimpleJWT blacklist), then removes the cookie.
 *
 * The cookie is cleared even when revocation fails (Django unreachable,
 * token already expired or revoked). `revoked` reports whether Django
 * confirmed the revocation; it is never claimed otherwise.
 */
export async function POST(request: NextRequest) {
  if (!isSameOrigin(request)) return json({ detail: "Forbidden." }, 403);

  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
  let revoked = false;
  if (refresh) {
    const result = await postToDjango("/api/auth/logout/", { refresh });
    revoked = result?.status === 200;
  }

  const response = json({ ok: true, revoked });
  clearRefreshCookie(response);
  return response;
}
