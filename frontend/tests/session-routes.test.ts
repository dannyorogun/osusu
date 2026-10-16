// @vitest-environment node
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { POST as login } from "@/app/api/session/login/route";
import { POST as logout } from "@/app/api/session/logout/route";
import { POST as refresh } from "@/app/api/session/refresh/route";
import { proxy } from "@/proxy";

import { jsonResponse, queuedFetch } from "./helpers";

const ORIGIN = "http://localhost:3000";
const REFRESH = "refresh-token-SECRET";

function request(path: string, init: { body?: unknown; cookie?: string; origin?: string | null } = {}) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (init.origin !== null) headers.set("Origin", init.origin ?? ORIGIN);
  if (init.cookie) headers.set("Cookie", init.cookie);
  return new NextRequest(`${ORIGIN}${path}`, {
    method: "POST",
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_URL", "http://django.test");
});

describe("POST /api/session/login", () => {
  it("returns only the access token and stores the refresh token httpOnly", async () => {
    const fetchMock = queuedFetch(jsonResponse(200, { access: "access-1", refresh: REFRESH }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await login(request("/api/session/login", { body: { username: "ada", password: "pw" } }));

    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toEqual({ access: "access-1" });
    expect(JSON.stringify(body)).not.toContain(REFRESH);

    const cookie = response.headers.get("set-cookie") ?? "";
    expect(cookie).toContain(`osusu_refresh=${REFRESH}`);
    expect(cookie).toMatch(/HttpOnly/i);
    expect(cookie).toMatch(/SameSite=strict/i);
    expect(response.headers.get("cache-control")).toBe("no-store");

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://django.test/api/auth/login/");
    expect(JSON.parse(String(init.body))).toEqual({ username: "ada", password: "pw" });
  });

  it("maps bad credentials to 401 without setting a cookie", async () => {
    vi.stubGlobal("fetch", queuedFetch(jsonResponse(401, { detail: "No active account found" })));

    const response = await login(request("/api/session/login", { body: { username: "ada", password: "x" } }));

    expect(response.status).toBe(401);
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("passes Django's login throttle through as 429 with Retry-After", async () => {
    const throttled = new Response(JSON.stringify({ detail: "Request was throttled. Expected available in 42 seconds." }), {
      status: 429,
      headers: { "Content-Type": "application/json", "Retry-After": "42" },
    });
    vi.stubGlobal("fetch", queuedFetch(throttled));

    const response = await login(request("/api/session/login", { body: { username: "ada", password: "x" } }));

    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("42");
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(await response.json()).toEqual({ detail: "Too many sign-in attempts. Please wait and try again." });
  });

  it("returns 503 when Django is unreachable", async () => {
    vi.stubGlobal("fetch", queuedFetch(new TypeError("fetch failed")));
    const response = await login(request("/api/session/login", { body: { username: "a", password: "b" } }));
    expect(response.status).toBe(503);
  });

  it("rejects cross-origin requests (CSRF)", async () => {
    const fetchMock = queuedFetch();
    vi.stubGlobal("fetch", fetchMock);
    const response = await login(request("/api/session/login", {
      body: { username: "a", password: "b" }, origin: "https://evil.example",
    }));
    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("behind a proxy, accepts the configured public origin and still rejects others", async () => {
    vi.stubEnv("OSUSU_APP_ORIGIN", "https://app.staging.example");
    const fetchMock = queuedFetch(jsonResponse(401, {}));
    vi.stubGlobal("fetch", fetchMock);

    // nextUrl is the internal address; the browser's Origin is the public one.
    const ok = await login(request("/api/session/login", {
      body: { username: "a", password: "b" }, origin: "https://app.staging.example",
    }));
    const internal = await login(request("/api/session/login", { body: { username: "a", password: "b" } }));
    const evil = await login(request("/api/session/login", {
      body: { username: "a", password: "b" }, origin: "https://evil.example",
    }));

    expect(ok.status).toBe(401); // reached Django
    expect(internal.status).toBe(403);
    expect(evil.status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects malformed bodies", async () => {
    vi.stubGlobal("fetch", queuedFetch());
    const response = await login(request("/api/session/login", { body: { username: 1 } }));
    expect(response.status).toBe(400);
  });
});

describe("POST /api/session/refresh", () => {
  it("exchanges the cookie for a new access token", async () => {
    const fetchMock = queuedFetch(jsonResponse(200, { access: "access-2" }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await refresh(request("/api/session/refresh", { cookie: `osusu_refresh=${REFRESH}` }));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ access: "access-2" });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ refresh: REFRESH });
  });

  it("without a cookie is 401 and never calls Django", async () => {
    const fetchMock = queuedFetch();
    vi.stubGlobal("fetch", fetchMock);
    const response = await refresh(request("/api/session/refresh"));
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("an expired refresh token clears the cookie", async () => {
    vi.stubGlobal("fetch", queuedFetch(jsonResponse(401, { detail: "Token is invalid or expired" })));

    const response = await refresh(request("/api/session/refresh", { cookie: `osusu_refresh=${REFRESH}` }));

    expect(response.status).toBe(401);
    expect(response.headers.get("set-cookie")).toMatch(/osusu_refresh=;.*Max-Age=0/i);
  });
});

describe("concurrent refreshes (rotation is off)", () => {
  it("two tabs refreshing with the same cookie both succeed and keep the cookie", async () => {
    // Django without rotation: the same refresh token is valid for both.
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, { access: "access-n" })));

    const [a, b] = await Promise.all([
      refresh(request("/api/session/refresh", { cookie: `osusu_refresh=${REFRESH}` })),
      refresh(request("/api/session/refresh", { cookie: `osusu_refresh=${REFRESH}` })),
    ]);

    for (const response of [a, b]) {
      expect(response.status).toBe(200);
      expect(await response.json()).toEqual({ access: "access-n" });
      // No Set-Cookie at all: neither response clears or replaces the session.
      expect(response.headers.get("set-cookie")).toBeNull();
    }
  });

  it("documents why rotation stays off: a losing concurrent refresh clears the cookie", async () => {
    // What blacklist-after-rotation would do: the first refresh rotates,
    // the second presents the now-blacklisted token.
    const responses = [
      jsonResponse(200, { access: "access-1", refresh: "refresh-2" }),
      jsonResponse(401, { detail: "Token is blacklisted", code: "token_not_valid" }),
    ];
    vi.stubGlobal("fetch", vi.fn(async () => responses.shift()!));

    const first = await refresh(request("/api/session/refresh", { cookie: `osusu_refresh=${REFRESH}` }));
    const second = await refresh(request("/api/session/refresh", { cookie: `osusu_refresh=${REFRESH}` }));

    expect(first.headers.get("set-cookie")).toContain("osusu_refresh=refresh-2");
    expect(second.status).toBe(401);
    expect(second.headers.get("set-cookie")).toMatch(/Max-Age=0/i); // would log the user out
  });
});

describe("POST /api/session/logout", () => {
  it("revokes the refresh token in Django, then clears the cookie", async () => {
    const fetchMock = queuedFetch(jsonResponse(200, {}));
    vi.stubGlobal("fetch", fetchMock);

    const response = await logout(request("/api/session/logout", { cookie: `osusu_refresh=${REFRESH}` }));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true, revoked: true });
    expect(response.headers.get("set-cookie")).toMatch(/Max-Age=0/i);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://django.test/api/auth/logout/");
    expect(JSON.parse(String(init.body))).toEqual({ refresh: REFRESH });
  });

  it("still clears the cookie when Django rejects the token", async () => {
    vi.stubGlobal("fetch", queuedFetch(jsonResponse(401, { detail: "Token is blacklisted" })));

    const response = await logout(request("/api/session/logout", { cookie: `osusu_refresh=${REFRESH}` }));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true, revoked: false });
    expect(response.headers.get("set-cookie")).toMatch(/Max-Age=0/i);
  });

  it("still clears the cookie when Django is unreachable", async () => {
    vi.stubGlobal("fetch", queuedFetch(new TypeError("fetch failed")));

    const response = await logout(request("/api/session/logout", { cookie: `osusu_refresh=${REFRESH}` }));

    expect(await response.json()).toEqual({ ok: true, revoked: false });
    expect(response.headers.get("set-cookie")).toMatch(/Max-Age=0/i);
  });

  it("does not call Django without a session cookie", async () => {
    const fetchMock = queuedFetch();
    vi.stubGlobal("fetch", fetchMock);

    const response = await logout(request("/api/session/logout"));

    expect(await response.json()).toEqual({ ok: true, revoked: false });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects cross-origin requests without revoking", async () => {
    const fetchMock = queuedFetch();
    vi.stubGlobal("fetch", fetchMock);

    const response = await logout(request("/api/session/logout", {
      cookie: `osusu_refresh=${REFRESH}`, origin: "https://evil.example",
    }));

    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("proxy (route protection is UX only)", () => {
  function page(path: string, cookie?: string) {
    return new NextRequest(`${ORIGIN}${path}`, {
      headers: cookie ? { Cookie: cookie } : undefined,
    });
  }

  it("redirects visitors without a session to /login with a next path", () => {
    const response = proxy(page("/circles/abc"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(`${ORIGIN}/login?next=%2Fcircles%2Fabc`);
  });

  it("lets a request with a session cookie through (Django still authorizes data)", () => {
    const response = proxy(page("/dashboard", `osusu_refresh=${REFRESH}`));
    expect(response.headers.get("location")).toBeNull();
  });
});
