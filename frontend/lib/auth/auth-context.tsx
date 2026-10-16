"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { osusu } from "@/lib/api/endpoints";
import { onSessionExpired } from "@/lib/api";
import { loginSession, logoutSession, refreshSession } from "@/lib/auth/session";
import { tokenStore } from "@/lib/auth/token-store";
import type { LoginRequest, User } from "@/types/user";

export type AuthState = {
  currentUser: User | null;
  isAuthenticated: boolean;
  /** True until the initial session check has finished. */
  isLoading: boolean;
  /** Throws ApiError on failure (401 = invalid credentials). */
  login: (credentials: LoginRequest) => Promise<User>;
  logout: () => Promise<void>;
  /** Re-fetch the current user (e.g. after a profile change). */
  refresh: () => Promise<User | null>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const loadUser = useCallback(async (): Promise<User | null> => {
    try {
      const user = await osusu.users.me();
      setCurrentUser(user);
      return user;
    } catch {
      setCurrentUser(null);
      return null;
    }
  }, []);

  // Restore a session after a reload: the access token was only in memory.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const token = tokenStore.get() ?? (await refreshSession().catch(() => null));
      tokenStore.set(token);
      if (token && !cancelled) await loadUser();
      if (!cancelled) setIsLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [loadUser]);

  // The API client ends the session when a refresh fails.
  useEffect(
    () =>
      onSessionExpired(() => {
        setCurrentUser(null);
        void logoutSession();
      }),
    [],
  );

  const login = useCallback(
    async (credentials: LoginRequest) => {
      const access = await loginSession(credentials);
      tokenStore.set(access);
      const user = await osusu.users.me();
      setCurrentUser(user);
      return user;
    },
    [],
  );

  const logout = useCallback(async () => {
    tokenStore.clear();
    setCurrentUser(null);
    await logoutSession();
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      currentUser,
      isAuthenticated: currentUser !== null,
      isLoading,
      login,
      logout,
      refresh: loadUser,
    }),
    [currentUser, isLoading, login, logout, loadUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>.");
  return context;
}
