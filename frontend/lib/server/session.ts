import { NextResponse, type NextRequest } from "next/server";

/**
 * Server-only helpers for the session route handlers (imported only by
 * app/api/session/*; never by client components).
 *
 * The Django refresh token is kept in an httpOnly, SameSite=Strict cookie
 * scoped to this Next.js origin: browser JavaScript can never read it and
 * it is never sent to Django by the browser. Only short-lived access
 * tokens are returned to the page.
 */

export const REFRESH_COOKIE = "osusu_refresh";

const DJANGO_TIMEOUT_MS = 10_000;

function djangoBaseUrl(): string {
  const url = process.env.OSUSU_API_URL || process.env.NEXT_PUBLIC_API_URL;
  if (!url) throw new Error("OSUSU_API_URL / NEXT_PUBLIC_API_URL is not configured.");
  return url.replace(/\/+$/, "");
}

function refreshMaxAge(): number {
  const value = Number(process.env.OSUSU_REFRESH_COOKIE_MAX_AGE ?? 86_400);
  return Number.isFinite(value) && value > 0 ? value : 86_400;
}

/**
 * This app's public origin. Behind a TLS reverse proxy `next start` sees
 * its internal address (request.nextUrl.origin is e.g.
 * http://localhost:3000 whatever Host/X-Forwarded-* say), so deployments
 * must set OSUSU_APP_ORIGIN (server-only, e.g. https://app.example.org).
 * Development falls back to the request's own origin.
 */
export function appOrigin(request: NextRequest): string {
  return process.env.OSUSU_APP_ORIGIN?.trim() || request.nextUrl.origin;
}

/**
 * CSRF defence for the cookie-authenticated session routes (in addition to
 * SameSite=Strict): only same-origin browser requests are accepted.
 */
export function isSameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  if (origin) return origin === appOrigin(request);
  return request.headers.get("sec-fetch-site") === "same-origin";
}

export function json(body: unknown, status = 200): NextResponse {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

export function setRefreshCookie(response: NextResponse, token: string): void {
  response.cookies.set(REFRESH_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/",
    maxAge: refreshMaxAge(),
  });
}

export function clearRefreshCookie(response: NextResponse): void {
  response.cookies.set(REFRESH_COOKIE, "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/",
    maxAge: 0,
  });
}

export type DjangoResult = {
  status: number;
  data: Record<string, unknown>;
  /** Django's Retry-After (seconds) on a 429, when sent. */
  retryAfter?: string | null;
};

/** POST JSON to Django. Returns null when Django is unreachable. */
export async function postToDjango(
  path: string,
  body: unknown,
): Promise<DjangoResult | null> {
  try {
    const response = await fetch(`${djangoBaseUrl()}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(DJANGO_TIMEOUT_MS),
    });
    let data: Record<string, unknown> = {};
    try {
      const parsed: unknown = await response.json();
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        data = parsed as Record<string, unknown>;
      }
    } catch {
      data = {};
    }
    return { status: response.status, data, retryAfter: response.headers.get("retry-after") };
  } catch {
    return null;
  }
}

export function stringField(data: Record<string, unknown>, key: string): string | null {
  const value = data[key];
  return typeof value === "string" && value ? value : null;
}
