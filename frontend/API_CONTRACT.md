# Osusu frontend ↔ Django API contract

Endpoints the frontend consumes **today**, taken from the Django source
(`backend/*/urls.py`, views and serializers) and its tests; last updated
2026-10-12 (Sprint 31). Nothing here is a planned endpoint. Types live in `types/`; calls in `lib/api/endpoints.ts`.

Conventions:
- JSON bodies. `DecimalField` values are **strings** (`"50.00"`); datetimes are
  ISO 8601; ids are UUID strings.
- CORS: only origins in `DJANGO_CORS_ALLOWED_ORIGINS` (development default
  `http://localhost:3000`, `http://127.0.0.1:3000`) receive CORS headers.
- Auth: `Authorization: Bearer <access>` (SimpleJWT). Access tokens live 5
  minutes, refresh tokens 1 day (SimpleJWT defaults; no `SIMPLE_JWT` settings,
  no rotation). Refresh tokens are revoked server-side on logout
  (`token_blacklist` app).
- Circle-scoped reads (`/api/circles/<id>/...`) all use the same rule: the
  requester must be an ACTIVE member. 404 `{"detail":"Circle not found."}` for
  a nonexistent circle **or** one the requester was never in (identical);
  403 `{"detail":"Only active circle members can access this circle."}` for
  invited/left/removed memberships; 401 unauthenticated; 405 for any write
  method. Lists are plain JSON arrays (no pagination; sizes are bounded per
  circle).
- Error bodies: `{"detail": "..."}` (401/403/404/405), serializer errors
  `{"field": ["..."]}`, circle/invitation domain errors `{"<verb>": false,
  "error": "..."}`, assistant errors `{"detail", "code", "request_id"}`.
- The browser shows its own friendly messages for 401/403/404/5xx and only
  shows backend text for 400 validation/domain messages.

## Session routes (Next.js, this app)

The backend returns tokens in JSON only. These route handlers keep the
refresh token in an `httpOnly; SameSite=Strict; Secure (production)` cookie
and hand the browser access tokens only. All reject cross-origin requests
(403).

| Route | Calls Django | Response |
|---|---|---|
| `POST /api/session/login` `{username, password}` | `POST /api/auth/login/` | 200 `{access}` + cookie; 400 field errors; 401 `{"detail":"Invalid credentials."}`; 429 `{"detail": "Too many sign-in attempts. ..."}` + Django's `Retry-After`; 503 if Django is unreachable |
| `POST /api/session/refresh` (cookie) | `POST /api/auth/refresh/` | 200 `{access}`; 401 no/expired session (cookie cleared); 503 |
| `POST /api/session/logout` (cookie) | `POST /api/auth/logout/` | 200 `{"ok": true, "revoked": boolean}`; the cookie is cleared **even if** revocation fails (`revoked: false` when Django is unreachable, rejects the token, or there was no cookie) |

## Django endpoints

### `POST /api/auth/login/`
- **Auth:** none. **Request:** `{"username": string, "password": string}` —
  username only (Django `USERNAME_FIELD`); email login is not supported.
- **Response 200:** `{"access": string, "refresh": string}`.
- **Errors:** 400 missing fields; 401 `{"detail": "No active account found with the given credentials"}`;
  429 `{"detail": "Request was throttled. ..."}` + `Retry-After` (per username, default 5/minute,
  and per client IP; `OSUSU_THROTTLE_*`).
- **Frontend:** only via `/api/session/login` (server side).

### `POST /api/auth/refresh/`
- **Auth:** none. **Request:** `{"refresh": string}`. **Response 200:** `{"access": string}`.
- **Errors:** 401 `{"detail": "...", "code": "token_not_valid"}` (invalid or expired).
- **Frontend:** only via `/api/session/refresh` (server side).

### `POST /api/auth/logout/`
- **Auth:** none (the access token may already have expired). **Request:**
  `{"refresh": string}`. **Response 200:** `{}`; the token is blacklisted and
  `POST /api/auth/refresh/` then returns 401 `{"detail": "Token is blacklisted", "code": "token_not_valid"}`.
- **Errors:** 400 missing `refresh`; 401 invalid, expired, already revoked, or
  an access token. Only that refresh token is revoked (other sessions stay valid).
- **Frontend:** only via `/api/session/logout` (server side).

### `POST /api/users/register/`
- **Auth:** none (`AllowAny`).
- **Request:** `{"email", "username", "first_name", "last_name", "password"}`.
  The password must pass Django's `AUTH_PASSWORD_VALIDATORS` (min length 8,
  not too similar to username/email/name, not common, not all numeric).
- **Response 201:** the same fields without `password`.
- **Errors:** 429 + `Retry-After` past the per-IP limit (default 10/hour).
  400 e.g. `{"email": ["user with this email already exists."]}`,
  `{"username": ["A user with that username already exists."]}`,
  `{"password": ["This password is too common.", "This password is entirely numeric."]}`
  (all failing validator messages; the password is never echoed).
- **Frontend:** `RegisterForm` → `osusu.users.register`, then signs in.

### `GET /api/users/me/`
- **Auth:** Bearer. **Response 200:** `User` — `id, email, username,
  first_name, last_name, is_verified, created_at, updated_at`.
- **Errors:** 401.
- **Frontend:** `AuthProvider` (current user), profile, dashboard greeting.

### `POST /api/circles/`
- **Auth:** Bearer.
- **Request (`CreateCircleSerializer`):** `name` (≤120), `description`
  (optional), `member_limit` (2–100), `contribution_amount` (≥0.01, 2 dp),
  `payout_amount` (≥0.01, 2 dp), `contribution_frequency` (free text, default
  `"weekly"`), `payout_frequency` (free text, default `"biweekly"`),
  `cycle_length` (≥1), `quorum_percentage` (1–100), `grace_period_days` (≥0),
  `reserve_enabled` (default false), `reserve_amount` (≥0), 
  `allow_replacement_before_lock` (default true).
- **Response 201:** `Circle` (below). The creator becomes an active member;
  status starts `"recruiting"`.
- **Errors:** 400 field errors; 401.
- **Frontend:** `CreateCircleForm` → redirect to `/circles/<id>`.

### `GET /api/circles/`
- **Auth:** Bearer. Returns only circles where the requester has an **ACTIVE**
  membership, newest first. Invited/left/removed memberships are not listed;
  pending invitations are not memberships (accepting one creates the ACTIVE
  membership).
- **Response 200:** `MyCircle[]` — `id, name, description, status,
  created_at, member_count` (ACTIVE memberships only), `constitution{member_limit,
  contribution_amount, contribution_frequency, payout_amount, payout_frequency,
  cycle_length}`.
- **Errors:** 401.
- **Frontend:** `/circles` (`MyCircles`), dashboard, payments and payouts pages.

### `GET /api/circles/<circle_id>/`
- **Auth:** Bearer; requester must be an ACTIVE member.
- **Response 200:** `Circle` — `id, name, description, status, created_at,
  updated_at, financial_locked_at, constitution{member_limit,
  contribution_amount, contribution_frequency, payout_amount,
  payout_frequency, cycle_length, quorum_percentage, grace_period_days,
  reserve_enabled, reserve_amount, allow_replacement_before_lock}`.
  `status` ∈ draft | recruiting | ready | locked | active | completed.
- **Errors:** 404 nonexistent circle or never a member (indistinguishable);
  403 invited/left/removed member.
- **Frontend:** circle detail page (Overview, Constitution tabs).

### `GET /api/circles/<circle_id>/members/`
- **Auth:** Bearer; ACTIVE member (see conventions).
- **Response 200:** `CircleMember[]` for ACTIVE and INVITED memberships
  (former LEFT/REMOVED members are not listed), ordered by join date —
  `id` (membership id), `display_name` (first + last name, else username),
  `username, status, joined_at, constitution_accepted,
  constitution_accepted_at, is_creator, is_you`. **No** email, user id,
  profile, or risk data.
- **Frontend:** circle → Members tab.

### `GET /api/circles/<circle_id>/obligations/`
- **Auth:** Bearer; ACTIVE member. Returns **only the requester's own**
  obligations in this circle — the creator gets no aggregate view.
- **Response 200:** `Obligation[]` ordered by `period_number` — `id,
  period_number, amount_due` (decimal string), `due_date, status`
  (pending | paid | overdue | waived), `paid_at` (null unless paid).
- **Frontend:** circle → Contributions tab; dashboard; `/payments`. Read-only:
  nothing in the frontend marks an obligation paid.

### `GET /api/circles/<circle_id>/payouts/`
- **Auth:** Bearer; ACTIVE member.
- **Response 200:** `{"payouts": Payout[], "open_windows": [{payout_window,
  candidate_count}]}`. `payouts` are rows with status **approved**
  (selected, not yet paid), **processing** (a payment attempt is submitted
  or its outcome is unknown: money may be moving; never shown as failed, never
  retried), **paid**, **failed** (the provider *confirmed* failure; nothing
  paid; may be executed again) or **returned** (paid, then returned by the
  provider; not paid), newest window first — `id, payout_window, amount,
  status, recipient` (display name), `is_you, created_at, approved_at,
  paid_at, attempt_state` (latest attempt: prepared | submitted | unknown |
  succeeded | failed | returned, or null).
  PENDING rows are candidates (PayoutEngine creates one per eligible member)
  and are only counted per window in `open_windows`; deciding a window
  cancels the losing candidates, which are never listed. Votes, voters and
  candidate identities are never returned. `paid` is set only by
  `PayoutCompletionService`, together with exactly one PAYOUT ledger entry.
  Voting, approval and execution: `payout-windows` below.
- **Frontend:** circle → Payouts tab; `/payouts`.

### Payout windows — `/api/circles/<circle_id>/payout-windows/...`
Thin views over `PayoutEngine`, `PayoutVoteService`, `PayoutApprovalService`
and `ExecutePayoutService`. Circle access as for every circle route
(404 outsider/unknown circle, 403 invited/left/removed). Domain refusals are
400 `{"error": "..."}`.

`PayoutWindow` = `{payout_window, state, candidates[{id, display_name, is_you,
status}], votes_cast, votes_required, your_vote, payout: Payout | null,
can_vote, can_approve, can_execute}`.
- `state` ∈ open | approved | processing | paid | failed | returned | closed.
- `votes_cast` / `votes_required` (the constitution's quorum of currently
  eligible voters, rounded up) only while open; otherwise null.
- `your_vote` is the requester's own candidate id; nobody else's vote, and no
  voter identity, is ever returned.
- `can_*` are hints for this user; the services re-check every request.

| Method & route | Who | Behaviour |
|---|---|---|
| `GET payout-windows/` | ACTIVE member | `{window: PayoutWindow \| null, can_open_window}` — the latest window. |
| `POST payout-windows/` | creator | Opens the next window (number chosen by the server). 201 `{window}`. 400 before the financial lock, while another window is unresolved, if the treasury cannot fund `payout_amount`, or if nobody is eligible. |
| `GET payout-windows/<n>/` | ACTIVE member | `{window}`; 404 `{"detail": "Payout window not found."}`. |
| `POST payout-windows/<n>/vote/` `{candidate_id}` | eligible ACTIVE member | 200 `{window}`. 400: `candidate_id` missing/invalid (field error); `"Candidate is not in this payout window."` (also for ids from other windows or circles); `"Only eligible members can vote."`; `"You have already voted in this payout window."`; `"Voting for this payout window has closed."`. Voting again for the same candidate is a no-op. |
| `POST payout-windows/<n>/approve/` | creator | Selects the most-voted candidate (ties: earliest), cancels the rest. 200 `{window}`; repeating it returns the same decision. 400 `{"error": "Quorum not reached: X of Y required votes.", window}`. 404 unknown window. |
| `POST payout-windows/<n>/execute/` | creator | 200 `{window, result: "paid"}` (settlement confirmed; only the development mock confirms synchronously); repeating it: 200 `{window, result: "already_paid"}` — no provider call, no second ledger entry. 202 `{window, result: "submitted", error}`: the provider accepted it, not yet settled. 202 `{window, result: "unknown", error}`: no definitive answer (timeout, connection loss); payout `processing`, **not** failed, not retried. 409 `{window, result: "in_progress", error}`: an earlier attempt is unresolved; nothing sent. 502 `{window, result: "failed", error}`: the provider confirmed failure; payout `failed`, nothing paid, may be executed again. 400 `"This payout was returned ..."` for a returned payout. 503 `{window, result: "unavailable", error}`: payouts are disabled on this server (no live payout provider; the production default) — nothing sent or recorded, payout stays `approved`. 400: `"This payout window has no approved payout."`, `"Treasury cannot fund this payout."`. |

- **Frontend:** circle → Payouts tab (`PayoutWindowPanel`). A payout is shown
  as paid only from a backend response.

### `GET /api/circles/<circle_id>/treasury/`
- **Auth:** Bearer; ACTIVE member.
- **Response 200:** `{balance, reserved_for_payouts, available_balance,
  completed_transaction_count, totals:{contribution, payout, refund, reserve,
  adjustment, adjustment_out, payout_return: {total, count}},
  pending_transaction_count, failed_transaction_count}`.
  `reserved_for_payouts` = amounts of `processing` payouts (no ledger row
  yet, so still inside `balance`); `available_balance` = balance − reserved.
  `payout_return` (incoming) compensates a returned payout's PAYOUT row. `balance` and
  `totals` come from `TreasuryEngine` over **completed** ledger rows only
  (contribution/reserve/adjustment in, payout/refund/adjustment_out out;
  `adjustment_out` = an operator's reviewed outgoing correction). Pending and failed
  rows are only counted. No individual ledger entries are returned.
- **Frontend:** circle → Treasury tab (shown as returned; nothing is summed in
  the browser).

### `GET /api/circles/<circle_id>/activity/`
- **Auth:** Bearer; ACTIVE member.
- **Response 200:** up to 50 `ActivityEvent`, newest first — `id, event,
  occurred_at, member` (display name of the user on the audit record, or null),
  `payout_window` (int or null). `event` ∈ circle_created | circle_ready |
  circle_locked | invitation_sent | member_joined | constitution_accepted |
  payout_window_opened | payout_approved | payout_completed |
  restructure_proposed. Votes and failed execution attempts are audited but
  not listed. Audit
  metadata is never passed through (no invitee emails, amounts, or provider
  references). Ledger events and any other audit action are excluded.
- **Frontend:** circle → Activity tab; dashboard "Recent activity".

### `GET /api/circles/<circle_id>/trust/`
- **Auth:** Bearer; ACTIVE member.
- **Response 200:** `{data_status, your_record_in_circle{total, pending, paid,
  overdue, waived}, your_history{completed_circles, paid_contributions,
  overdue_contributions}, circle{active_members, invitation_connections},
  score: null, score_unavailable_reasons: string[]}`.
  - `your_*` are the **requester's own** counts (`your_history` spans every
    circle, via `TrustFeatureEngine.compute`); no other member's record is
    returned.
  - `data_status` is `insufficient_data` until the requester has at least
    one paid or overdue obligation; it does not mean low trust.
  - `invitation_connections` is a count of invitation relationships among
    current and former members; who invited whom is never returned.
  - `score` is always null: the existing reliability and circle-health
    formulas are unvalidated and treat missing data as perfect, and shared
    successful cycles are never recorded. The reasons are returned verbatim.
- **Frontend:** circle → Trust tab.

### `GET /api/users/me/obligations/`
- **Auth:** Bearer. Takes no user parameter (any query parameter is ignored).
- **Response 200:** the requester's own obligations in every circle where
  they are an ACTIVE member, soonest due first — the
  `/api/circles/<id>/obligations/` fields plus `circle{id, name}`.
- **Frontend:** dashboard summary, `/payments` (one request, not one per circle).

### `POST /api/circles/<circle_id>/invite/`
- **Auth:** Bearer; ACTIVE member (any active member, not only the creator —
  the existing `InvitationService` rule). **Request:** `{"email": string}`.
- **Response 201:** `{invited: true, invitation_id, email, expires_at, token}`.
  Osusu sends no email: the inviter shares `token` with the invitee.
  Invitations expire after 7 days.
- **Errors:** 400 `{"invited": false, "error": "..."}` — email missing, circle
  not recruiting, member limit reached, already a member, pending invitation
  exists. 403/404 as for every circle route.
- **Frontend:** circle → Set up tab.

### `POST /api/circles/invitations/<token>/accept/`
- **Auth:** Bearer. **Request:** empty. The invitation's email must match the
  signed-in user's.
- **Response 200:** `{"accepted": true, "circle_id", "membership_id", "status"}`
  (creates an ACTIVE membership).
- **Errors:** 404 unknown token; 400 `{"accepted": false, "error": ...}` with
  `"Invitation has expired."`, `"Invitation is no longer valid."` (accepted
  or revoked), `"This invitation was not sent to your email address."`,
  circle no longer recruiting, member limit, already a member.
- **Frontend:** `AcceptInvitation` modal on `/circles` → redirect to circle.

### `POST /api/circles/<circle_id>/accept-constitution/`
- **Auth:** Bearer; ACTIVE member. **Request:** empty.
- **Response 200:** `{accepted: true, circle_id, membership_id, accepted_at}`;
  repeating it changes nothing (one audit record).
- **Errors:** 400 `{"accepted": false, "error": "The circle constitution can no
  longer be accepted."}` once the circle is locked, active or completed.
- **Frontend:** circle → Set up tab. Acceptance per member is shown from
  `/members/` (`constitution_accepted`).

### `POST /api/circles/<circle_id>/evaluate/`
- **Auth:** Bearer; creator (and ACTIVE member); others 403/404.
- **Response 200:** `{ready, formation_checks{<check>: bool}, financial_checks
  {passed, checks{<check>: bool}, ...} | null, cash_flow{passed, failures,
  ...} | null}`. A passing evaluation moves the circle from draft/recruiting
  to **ready** (one `CIRCLE_READY` audit record; re-evaluating a ready circle
  reports without re-recording). A failing one changes nothing.
  `financial_checks` / `cash_flow` also contain amounts serialized as JSON
  numbers; the frontend shows only the booleans.
- **Errors:** 400 `{"ready": false, "error": "Formation can only be evaluated
  before the financial lock."}` for locked/active/completed circles.
- **Frontend:** circle → Set up tab (creator only).

### `POST /api/circles/<circle_id>/lock/`
- **Auth:** Bearer; creator (and ACTIVE member). Irreversible.
- **Response 200:** `{locked: true, circle: Circle}` (status `locked`,
  `financial_locked_at` set, `CIRCLE_LOCKED` audited). `FinancialLockEngine`
  re-checks every requirement under a row lock.
- **Errors:** 400 `{"locked": false, "error": "Circle cannot be financially
  locked.", "checks": {cash_flow_valid, circle_ready, formation_valid,
  financial_integrity}}` — includes a second lock attempt.
- **Frontend:** circle → Set up tab (creator only; offered only while the
  backend reports status `ready`, with a confirmation step).

### `POST /api/circles/<circle_id>/assistant/`
- **Auth:** Bearer; active member; rate limited per user (429 + `Retry-After`).
- **Request:** `{"question": string}` (≤1000 chars; no other fields).
- **Response 200:** `{request_id, status, answer, citations[], prompt_version,
  knowledge_schema_version, informational_only}`.
- **Errors:** 503 `{"code": "assistant_unavailable"}` — **always, today**: the
  backend readiness gate keeps the assistant disabled; 502 unverifiable
  output; 400/403/404.
- **Frontend:** `AssistantPanel` (circle → Assistant tab) shows 503 as
  "currently unavailable". The browser never generates answers.

### `POST /api/payments/obligations/<obligation_id>/create/`
- **Auth:** Bearer; the obligation must belong to the requester (403 otherwise).
- **Response 201:** `{id, provider, provider_payment_id, amount, currency,
  status, checkout_url}` — starts a provider payment; it does **not** mark the
  obligation paid (the provider webhook does, server side).
- **Frontend:** typed wrapper only (`osusu.payments.create`). Not offered in
  the UI: no real payment provider is connected yet, so `/payments` lists
  obligations without a pay action.

## Existing endpoints not used by the frontend yet

`GET /api/risk/circles/<id>/members/<member_id>/default-risk/` (a model
signal; deliberately not shown to members).
`POST /api/payments/webhooks/mock/` is development-only and server-to-server;
the frontend must never call it.
