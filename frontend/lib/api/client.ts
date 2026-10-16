import { ApiError } from "./errors";

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export type ApiClientOptions = {
  baseUrl: () => string;
  /** Current in-memory access token, if any. */
  getAccessToken: () => string | null;
  /**
   * Obtain a new access token (via the session refresh route). Resolves
   * null when the session cannot be refreshed.
   */
  refreshAccessToken: () => Promise<string | null>;
  /** Called once when the session is definitively over. */
  onSessionExpired: () => void;
  fetchImpl?: typeof fetch;
};

export type RequestOptions = {
  body?: unknown;
  /** Send without the Authorization header (e.g. registration). */
  anonymous?: boolean;
  signal?: AbortSignal;
};

/**
 * The single place the browser talks to Django.
 *
 * 401 handling: refresh the access token ONCE (concurrent 401s share one
 * refresh), retry the request ONCE, and if it still fails end the session.
 * There is no loop: a retried request is never refreshed again.
 * Tokens are never logged or included in errors.
 */
export function createApiClient(options: ApiClientOptions) {
  const fetchImpl = options.fetchImpl ?? ((...args) => fetch(...args));
  let refreshing: Promise<string | null> | null = null;

  function refreshOnce(): Promise<string | null> {
    if (!refreshing) {
      refreshing = options
        .refreshAccessToken()
        .catch(() => null)
        .finally(() => {
          refreshing = null;
        });
    }
    return refreshing;
  }

  async function send(
    method: HttpMethod,
    path: string,
    request: RequestOptions,
    token: string | null,
  ): Promise<Response> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (request.body !== undefined) headers["Content-Type"] = "application/json";
    if (token && !request.anonymous) headers.Authorization = `Bearer ${token}`;

    try {
      return await fetchImpl(`${options.baseUrl()}${path}`, {
        method,
        headers,
        body: request.body === undefined ? undefined : JSON.stringify(request.body),
        signal: request.signal,
        // Tokens travel in the Authorization header, never cookies.
        credentials: "omit",
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new ApiError(0);
    }
  }

  async function parse<T>(response: Response): Promise<T> {
    if (response.status === 204) return undefined as T;
    const text = await response.text();
    if (!text) return undefined as T;
    try {
      return JSON.parse(text) as T;
    } catch {
      // A non-JSON success (e.g. an HTML error page behind a proxy).
      throw new ApiError(502);
    }
  }

  async function errorFrom(response: Response): Promise<ApiError> {
    let body: unknown;
    try {
      body = JSON.parse(await response.text());
    } catch {
      body = undefined; // HTML debug pages etc. are never surfaced
    }
    return new ApiError(response.status, body);
  }

  async function request<T>(
    method: HttpMethod,
    path: string,
    request: RequestOptions = {},
  ): Promise<T> {
    let response = await send(method, path, request, options.getAccessToken());

    if (response.status === 401 && !request.anonymous) {
      const token = await refreshOnce();
      if (!token) {
        options.onSessionExpired();
        throw new ApiError(401);
      }
      response = await send(method, path, request, token);
      if (response.status === 401) {
        options.onSessionExpired();
        throw new ApiError(401);
      }
    }

    if (!response.ok) throw await errorFrom(response);
    return parse<T>(response);
  }

  return {
    request,
    get: <T>(path: string, o?: Omit<RequestOptions, "body">) =>
      request<T>("GET", path, o),
    post: <T>(path: string, body?: unknown, o?: RequestOptions) =>
      request<T>("POST", path, { ...o, body }),
    put: <T>(path: string, body?: unknown, o?: RequestOptions) =>
      request<T>("PUT", path, { ...o, body }),
    patch: <T>(path: string, body?: unknown, o?: RequestOptions) =>
      request<T>("PATCH", path, { ...o, body }),
    delete: <T>(path: string, o?: Omit<RequestOptions, "body">) =>
      request<T>("DELETE", path, o),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
