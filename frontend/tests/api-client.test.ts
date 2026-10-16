import { describe, expect, it, vi } from "vitest";

import { createApiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

import { jsonResponse, queuedFetch } from "./helpers";

const TOKEN = "access-token-SECRET";
const NEW_TOKEN = "access-token-NEW";

function setup(fetchImpl: typeof fetch, refresh = vi.fn(async () => NEW_TOKEN as string | null)) {
  let token: string | null = TOKEN;
  const onSessionExpired = vi.fn();
  const client = createApiClient({
    baseUrl: () => "http://api.test",
    getAccessToken: () => token,
    refreshAccessToken: async () => {
      token = await refresh();
      return token;
    },
    onSessionExpired,
    fetchImpl,
  });
  return { client, refresh, onSessionExpired };
}

function authHeader(call: unknown[]): string | undefined {
  const init = call[1] as RequestInit;
  return (init.headers as Record<string, string>).Authorization;
}

describe("api client", () => {
  it("sends the bearer token and parses JSON", async () => {
    const fetchImpl = queuedFetch(jsonResponse(200, { id: "1" }));
    const { client } = setup(fetchImpl);

    await expect(client.get("/api/users/me/")).resolves.toEqual({ id: "1" });

    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api.test/api/users/me/");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("omit");
    expect(authHeader(fetchImpl.mock.calls[0])).toBe(`Bearer ${TOKEN}`);
  });

  it("sends JSON bodies for POST/PUT/PATCH and supports DELETE", async () => {
    const fetchImpl = queuedFetch(
      jsonResponse(201, { ok: 1 }),
      jsonResponse(200, { ok: 2 }),
      jsonResponse(200, { ok: 3 }),
      new Response(null, { status: 204 }),
    );
    const { client } = setup(fetchImpl);

    await client.post("/a/", { x: 1 });
    await client.put("/a/", { x: 2 });
    await client.patch("/a/", { x: 3 });
    await expect(client.delete("/a/")).resolves.toBeUndefined();

    const methods = fetchImpl.mock.calls.map((c) => (c as unknown as [string, RequestInit])[1].method);
    expect(methods).toEqual(["POST", "PUT", "PATCH", "DELETE"]);
    expect((fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1].body).toBe('{"x":1}');
  });

  it("anonymous requests carry no Authorization header", async () => {
    const fetchImpl = queuedFetch(jsonResponse(201, {}));
    const { client } = setup(fetchImpl);

    await client.post("/api/users/register/", {}, { anonymous: true });

    expect(authHeader(fetchImpl.mock.calls[0])).toBeUndefined();
  });

  it("on 401 refreshes once and retries once with the new token", async () => {
    const fetchImpl = queuedFetch(jsonResponse(401, { detail: "expired" }), jsonResponse(200, { ok: true }));
    const { client, refresh, onSessionExpired } = setup(fetchImpl);

    await expect(client.get("/x/")).resolves.toEqual({ ok: true });

    expect(refresh).toHaveBeenCalledTimes(1);
    expect(authHeader(fetchImpl.mock.calls[1])).toBe(`Bearer ${NEW_TOKEN}`);
    expect(onSessionExpired).not.toHaveBeenCalled();
  });

  it("ends the session when the refresh fails (no retry)", async () => {
    const fetchImpl = queuedFetch(jsonResponse(401, {}));
    const { client, onSessionExpired } = setup(fetchImpl, vi.fn(async () => null));

    const error = await client.get("/x/").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).kind).toBe("unauthenticated");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(onSessionExpired).toHaveBeenCalledTimes(1);
  });

  it("never loops: a retried request that is still 401 ends the session", async () => {
    const fetchImpl = queuedFetch(jsonResponse(401, {}), jsonResponse(401, {}));
    const { client, refresh, onSessionExpired } = setup(fetchImpl);

    await expect(client.get("/x/")).rejects.toMatchObject({ status: 401 });

    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(onSessionExpired).toHaveBeenCalledTimes(1);
  });

  it("concurrent 401s share a single refresh", async () => {
    const fetchImpl = queuedFetch(
      jsonResponse(401, {}),
      jsonResponse(401, {}),
      jsonResponse(200, { n: 1 }),
      jsonResponse(200, { n: 2 }),
    );
    let release: (value: string) => void = () => {};
    const refresh = vi.fn(() => new Promise<string | null>((resolve) => (release = resolve)));
    const { client } = setup(fetchImpl, refresh);

    const both = Promise.all([client.get("/a/"), client.get("/b/")]);
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    release(NEW_TOKEN);

    await expect(both).resolves.toHaveLength(2);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it.each([
    [403, "forbidden"],
    [404, "not_found"],
    [429, "rate_limited"],
    [500, "server"],
    [503, "unavailable"],
  ] as const)("maps %i to a friendly %s error without backend text", async (status, kind) => {
    const fetchImpl = queuedFetch(
      jsonResponse(status, { detail: "Traceback (most recent call last): secret internals" }),
    );
    const { client, refresh } = setup(fetchImpl);

    const error = (await client.get("/x/").catch((e: unknown) => e)) as ApiError;

    expect(error.kind).toBe(kind);
    expect(error.message).not.toContain("Traceback");
    expect(refresh).not.toHaveBeenCalled();
  });

  it("keeps backend codes (e.g. assistant_unavailable) for the UI", async () => {
    const fetchImpl = queuedFetch(
      jsonResponse(503, { detail: "x", code: "assistant_unavailable", request_id: "r1" }),
    );
    const { client } = setup(fetchImpl);

    const error = (await client.post("/x/").catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe("assistant_unavailable");
    expect(error.requestId).toBe("r1");
  });

  it("exposes 400 validation messages per field", async () => {
    const fetchImpl = queuedFetch(
      jsonResponse(400, {
        username: ["A user with that username already exists."],
        non_field_errors: ["Something about the form."],
      }),
    );
    const { client } = setup(fetchImpl);

    const error = (await client.post("/x/", {}).catch((e: unknown) => e)) as ApiError;

    expect(error.kind).toBe("validation");
    expect(error.fieldMessage("username")).toBe("A user with that username already exists.");
    expect(error.formMessages).toEqual(["Something about the form."]);
  });

  it("maps domain {error} bodies to a form message", async () => {
    const fetchImpl = queuedFetch(jsonResponse(400, { accepted: false, error: "Invitation expired." }));
    const { client } = setup(fetchImpl);

    const error = (await client.post("/x/").catch((e: unknown) => e)) as ApiError;
    expect(error.formMessages).toEqual(["Invitation expired."]);
  });

  it("maps network failures and non-JSON bodies safely", async () => {
    const { client } = setup(queuedFetch(new TypeError("Failed to fetch")));
    await expect(client.get("/x/")).rejects.toMatchObject({ kind: "network", status: 0 });

    const html = new Response("<html>Django debug page</html>", { status: 500 });
    const second = setup(queuedFetch(html));
    const error = (await second.client.get("/x/").catch((e: unknown) => e)) as ApiError;
    expect(error.kind).toBe("server");
    expect(error.message).not.toContain("Django");
  });

  it("never puts the token in an error", async () => {
    const fetchImpl = queuedFetch(jsonResponse(500, { detail: `bad ${TOKEN}` }));
    const { client } = setup(fetchImpl);

    const error = (await client.get("/x/").catch((e: unknown) => e)) as ApiError;
    expect(JSON.stringify({ ...error, message: error.message })).not.toContain(TOKEN);
  });
});
