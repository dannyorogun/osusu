/**
 * Browser side of the session routes (app/api/session/*). These run on the
 * Next.js server, which holds the refresh token in an httpOnly cookie and
 * returns only short-lived access tokens to the browser.
 */

import { ApiError } from "@/lib/api/errors";
import type { LoginRequest } from "@/types/user";

type AccessResponse = { access: string };

async function post(path: string, body?: unknown): Promise<Response> {
  try {
    return await fetch(path, {
      method: "POST",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0);
  }
}

async function readAccess(response: Response): Promise<string | null> {
  try {
    const data = (await response.json()) as Partial<AccessResponse>;
    return typeof data.access === "string" ? data.access : null;
  } catch {
    return null;
  }
}

/** Throws ApiError (401 = invalid credentials) on failure. */
export async function loginSession(credentials: LoginRequest): Promise<string> {
  const response = await post("/api/session/login", credentials);
  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = undefined;
    }
    throw new ApiError(response.status, body);
  }
  const access = await readAccess(response);
  if (!access) throw new ApiError(502);
  return access;
}

/** A fresh access token, or null when there is no valid session. */
export async function refreshSession(): Promise<string | null> {
  const response = await post("/api/session/refresh");
  return response.ok ? readAccess(response) : null;
}

export async function logoutSession(): Promise<void> {
  try {
    await post("/api/session/logout");
  } catch {
    // The cookie is also cleared server-side on the next failed refresh.
  }
}
