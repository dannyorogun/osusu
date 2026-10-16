# Osusu frontend

Next.js 16 (App Router) · React 19 · TypeScript · Tailwind CSS 4. It consumes
the Django REST API in `../backend`; the backend is authoritative for every
financial value, permission and circle state. See `API_CONTRACT.md`.

> Next.js 16 differs from older versions (e.g. `middleware.ts` is now
> `proxy.ts`, route `params` are promises). Check `node_modules/next/dist/docs/`.

## Setup

```bash
cp .env.example .env.local   # set NEXT_PUBLIC_API_URL (e.g. http://localhost:8000)
npm install
npm run dev                   # http://localhost:3000 (Django on :8000)
```

| Script | |
|---|---|
| `npm run dev` / `build` / `start` | Next.js |
| `npm run lint` | ESLint |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | Vitest + Testing Library (no Django needed) |

Environments (development / staging / production) differ only by
environment variables: `NEXT_PUBLIC_API_URL` (browser → Django),
`OSUSU_API_URL` (server → Django, optional), `OSUSU_REFRESH_COOKIE_MAX_AGE`.
Never put secrets in `NEXT_PUBLIC_*`.

## Structure

```
app/
  (auth)/login, register        public auth pages
  (app)/…                       signed-in pages (RequireAuth + AppShell)
    dashboard, circles, circles/new, circles/[circleId],
    payments, payouts, trust, assistant, profile
  api/session/{login,refresh,logout}   session route handlers (BFF)
components/ui        design system (Button, Field, Surface, Table, Modal, …)
components/layout    AppShell, navigation
components/auth      LoginForm, RegisterForm, RequireAuth
components/circles   circle list/detail sections, create form, assistant panel
lib/api              client (fetch wrapper), errors, typed endpoints
lib/auth             AuthProvider/useAuth, in-memory token store, session calls
lib/server           server-only session helpers
types/               API response/request types (mirroring serializers)
proxy.ts             optimistic route protection (UX only)
tests/               Vitest suites
```

## Authentication

- Login goes through `POST /api/session/login` (this app), which calls
  Django and stores the **refresh token in an httpOnly, SameSite=Strict
  cookie** (Secure in production). Browser JavaScript never sees it.
- The **access token lives only in memory**. After a reload,
  `AuthProvider` calls `/api/session/refresh` to get a new one.
- API calls go straight from the browser to Django with
  `Authorization: Bearer`. On a 401 the client refreshes **once** (shared by
  concurrent requests), retries **once**, then signs the user out.
- `proxy.ts` redirects visitors without the cookie to `/login`. This is UX,
  not authorization: Django authorizes every request.
- Logout revokes the refresh token in Django (SimpleJWT blacklist) and
  always clears the cookie, even if revocation fails. Access tokens are not
  revocable and stay valid until they expire (5 minutes).
- The session routes require HTTPS in production (the cookie is `Secure`).
