import { act, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";
import { AuthProvider, useAuth, type AuthState } from "@/lib/auth/auth-context";
import * as session from "@/lib/auth/session";
import { tokenStore } from "@/lib/auth/token-store";

import { USER, jsonResponse, queuedFetch } from "./helpers";

vi.mock("@/lib/auth/session", () => ({
  loginSession: vi.fn(),
  refreshSession: vi.fn(),
  logoutSession: vi.fn(async () => undefined),
}));

const mocked = vi.mocked(session);

/** Latest auth state, captured after each render for the assertions. */
const auth = {} as AuthState;

function Probe() {
  const value = useAuth();
  useEffect(() => {
    Object.assign(auth, value);
  });
  if (value.isLoading) return <p>loading</p>;
  return <p>{value.isAuthenticated ? `signed in as ${value.currentUser?.username}` : "signed out"}</p>;
}

function renderAuth() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

beforeEach(() => {
  tokenStore.clear();
  mocked.loginSession.mockReset();
  mocked.refreshSession.mockReset();
  mocked.logoutSession.mockReset().mockResolvedValue(undefined);
});

describe("AuthProvider", () => {
  it("starts signed out when there is no session", async () => {
    mocked.refreshSession.mockResolvedValue(null);
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    renderAuth();

    expect(screen.getByText("loading")).toBeInTheDocument();
    expect(await screen.findByText("signed out")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("restores a session after reload from the refresh cookie", async () => {
    mocked.refreshSession.mockResolvedValue("access-1");
    vi.stubGlobal("fetch", queuedFetch(jsonResponse(200, USER)));

    renderAuth();

    expect(await screen.findByText("signed in as ada")).toBeInTheDocument();
    expect(tokenStore.get()).toBe("access-1");
  });

  it("treats a failing refresh (e.g. network) as signed out", async () => {
    mocked.refreshSession.mockRejectedValue(new ApiError(0));

    renderAuth();

    expect(await screen.findByText("signed out")).toBeInTheDocument();
  });

  it("login success loads the current user", async () => {
    mocked.refreshSession.mockResolvedValue(null);
    mocked.loginSession.mockResolvedValue("access-2");
    renderAuth();
    await screen.findByText("signed out");
    vi.stubGlobal("fetch", queuedFetch(jsonResponse(200, USER)));

    await act(() => auth.login({ username: "ada", password: "correct horse" }));

    expect(screen.getByText("signed in as ada")).toBeInTheDocument();
    expect(mocked.loginSession).toHaveBeenCalledWith({ username: "ada", password: "correct horse" });
    expect(tokenStore.get()).toBe("access-2");
  });

  it("login failure keeps the user signed out and reports the error", async () => {
    mocked.refreshSession.mockResolvedValue(null);
    mocked.loginSession.mockRejectedValue(new ApiError(401));
    renderAuth();
    await screen.findByText("signed out");

    await expect(auth.login({ username: "ada", password: "wrong" })).rejects.toMatchObject({
      status: 401,
    });
    expect(screen.getByText("signed out")).toBeInTheDocument();
    expect(tokenStore.get()).toBeNull();
  });

  it("logout clears the user, the token and the session cookie", async () => {
    mocked.refreshSession.mockResolvedValue("access-1");
    vi.stubGlobal("fetch", queuedFetch(jsonResponse(200, USER)));
    renderAuth();
    await screen.findByText("signed in as ada");

    await act(() => auth.logout());

    expect(screen.getByText("signed out")).toBeInTheDocument();
    expect(tokenStore.get()).toBeNull();
    expect(mocked.logoutSession).toHaveBeenCalledTimes(1);
  });

  it("an expired session whose refresh fails signs the user out", async () => {
    mocked.refreshSession.mockResolvedValueOnce("access-1");
    vi.stubGlobal("fetch", queuedFetch(jsonResponse(200, USER), jsonResponse(401, {})));
    renderAuth();
    await screen.findByText("signed in as ada");

    mocked.refreshSession.mockResolvedValueOnce(null); // refresh token expired
    await act(async () => {
      await auth.refresh();
    });

    await waitFor(() => expect(screen.getByText("signed out")).toBeInTheDocument());
    expect(tokenStore.get()).toBeNull();
    expect(mocked.logoutSession).toHaveBeenCalled();
  });

  it("an expired access token is refreshed transparently", async () => {
    mocked.refreshSession.mockResolvedValueOnce("access-1");
    const fetchMock = queuedFetch(
      jsonResponse(200, USER),
      jsonResponse(401, {}),
      jsonResponse(200, { ...USER, first_name: "Adaeze" }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderAuth();
    await screen.findByText("signed in as ada");

    mocked.refreshSession.mockResolvedValueOnce("access-2");
    await act(async () => {
      await auth.refresh();
    });

    expect(auth.currentUser?.first_name).toBe("Adaeze");
    expect(tokenStore.get()).toBe("access-2");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
