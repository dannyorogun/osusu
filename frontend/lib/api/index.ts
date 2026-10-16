import { apiBaseUrl } from "@/lib/config";
import { refreshSession } from "@/lib/auth/session";
import { tokenStore } from "@/lib/auth/token-store";

import { createApiClient } from "./client";

type Listener = () => void;
const expiryListeners = new Set<Listener>();

/** AuthProvider subscribes to learn when a session can't be refreshed. */
export function onSessionExpired(listener: Listener): () => void {
  expiryListeners.add(listener);
  return () => expiryListeners.delete(listener);
}

/** The application's Django API client. */
export const api = createApiClient({
  baseUrl: apiBaseUrl,
  getAccessToken: tokenStore.get,
  refreshAccessToken: async () => {
    const token = await refreshSession();
    tokenStore.set(token);
    return token;
  },
  onSessionExpired: () => {
    tokenStore.clear();
    expiryListeners.forEach((listener) => listener());
  },
});
