import type { NextRequest } from "next/server";

import {
  REFRESH_COOKIE,
  clearRefreshCookie,
  isSameOrigin,
  json,
  postToDjango,
  setRefreshCookie,
  stringField,
} from "@/lib/server/session";

/**
 * POST /api/session/refresh -> a new access token from the httpOnly
 * refresh cookie. An invalid/expired refresh token clears the cookie.
 */
export async function POST(request: NextRequest) {
  if (!isSameOrigin(request)) return json({ detail: "Forbidden." }, 403);

  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
  if (!refresh) return json({ detail: "No session." }, 401);

  const result = await postToDjango("/api/auth/refresh/", { refresh });
  if (!result) return json({ detail: "Service unavailable." }, 503);

  if (result.status === 200) {
    const access = stringField(result.data, "access");
    if (!access) return json({ detail: "Bad gateway." }, 502);

    const response = json({ access });
    // If Django ever enables ROTATE_REFRESH_TOKENS, keep the new one.
    const rotated = stringField(result.data, "refresh");
    if (rotated) setRefreshCookie(response, rotated);
    return response;
  }

  if (result.status === 400 || result.status === 401) {
    const response = json({ detail: "Session expired." }, 401);
    clearRefreshCookie(response);
    return response;
  }

  return json({ detail: "Service unavailable." }, 503);
}
