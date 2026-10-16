import type { NextRequest } from "next/server";

import {
  isSameOrigin,
  json,
  postToDjango,
  setRefreshCookie,
  stringField,
} from "@/lib/server/session";

/**
 * POST /api/session/login {username, password}
 * -> Django POST /api/auth/login/ -> refresh token stored in an httpOnly
 * cookie; only the access token is returned to the browser.
 */
export async function POST(request: NextRequest) {
  if (!isSameOrigin(request)) return json({ detail: "Forbidden." }, 403);

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return json({ detail: "Invalid request." }, 400);
  }
  const { username, password } = (body ?? {}) as Record<string, unknown>;
  if (typeof username !== "string" || typeof password !== "string") {
    return json({ detail: "Invalid request." }, 400);
  }

  const result = await postToDjango("/api/auth/login/", { username, password });
  if (!result) return json({ detail: "Service unavailable." }, 503);

  if (result.status === 200) {
    const access = stringField(result.data, "access");
    const refresh = stringField(result.data, "refresh");
    if (!access || !refresh) return json({ detail: "Bad gateway." }, 502);

    const response = json({ access });
    setRefreshCookie(response, refresh);
    return response;
  }

  if (result.status === 400) {
    // Field validation (e.g. "This field may not be blank.").
    return json(result.data, 400);
  }

  if (result.status === 401) {
    return json({ detail: "Invalid credentials." }, 401);
  }

  if (result.status === 429) {
    // Django's login throttle (per username / per IP).
    const response = json({ detail: "Too many sign-in attempts. Please wait and try again." }, 429);
    if (result.retryAfter && /^\d+$/.test(result.retryAfter)) {
      response.headers.set("Retry-After", result.retryAfter);
    }
    return response;
  }

  return json({ detail: "Service unavailable." }, result.status >= 500 ? 503 : 502);
}
