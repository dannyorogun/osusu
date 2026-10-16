/**
 * The access token lives ONLY in this module's memory: never in
 * localStorage, sessionStorage or a JavaScript-readable cookie. A page
 * reload drops it; the session route re-issues one from the httpOnly
 * refresh cookie. The refresh token is never visible to browser code.
 */

let accessToken: string | null = null;

export const tokenStore = {
  get: (): string | null => accessToken,
  set: (token: string | null): void => {
    accessToken = token;
  },
  clear: (): void => {
    accessToken = null;
  },
};
