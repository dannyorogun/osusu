# Operations notes

## Production deployment

Nothing here deploys anything; it is the configuration a deployment must
provide. Production = `DJANGO_DEBUG` unset or false.

### Environment

| Variable | Required | Notes |
|---|---|---|
| `DJANGO_SECRET_KEY` | yes | Also signs JWTs. Startup fails without it. From a secret store, never the repo. Rotating it logs everyone out. |
| `DJANGO_ALLOWED_HOSTS` | yes | API host name(s), comma-separated. |
| `DJANGO_CORS_ALLOWED_ORIGINS` | yes, for the frontend | Exact `https://` origin(s) of the Next.js app, comma-separated. No wildcards or paths (startup fails). Empty = no browser origin may call the API. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | if admin is served behind another origin | `https://` origins for Django admin form posts. |
| `DJANGO_SECURE_SSL_REDIRECT` | no (default true) | Set false only if the proxy already redirects HTTP. |
| `DJANGO_TRUST_X_FORWARDED_PROTO` | behind a TLS-terminating proxy | `true` only if that proxy always overwrites `X-Forwarded-Proto`. Otherwise HTTPS detection is spoofable (or every request redirects forever). |
| `DJANGO_NUM_PROXIES` | behind proxies (default 0) | Trusted proxies that append `X-Forwarded-For`; used for per-IP throttles. 0 = socket address only. |
| `DJANGO_SECURE_HSTS_SECONDS` | no (default 3600) | Raise to 31536000 once HTTPS is confirmed stable. Browsers remember it; lowering later does not help visitors who already saw it. |
| `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS`, `DJANGO_SECURE_HSTS_PRELOAD` | no (default false) | Only when every subdomain is HTTPS-only. Preload is effectively irreversible. Without them `check --deploy` reports W005/W021. |
| `OSUSU_THROTTLE_LOGIN_USERNAME` | no (`5/minute`) | Login attempts per username, any address. |
| `OSUSU_THROTTLE_LOGIN_IP` | no (`60/minute`) | Login attempts per client IP. Calls through the Next.js session route all come from the Next.js server's address, so this is a shared ceiling for them; size it for peak logins. |
| `OSUSU_THROTTLE_REGISTER_IP` | no (`10/hour`) | Registrations per client IP. |
| `OSUSU_PAYOUT_PROVIDER` | no (`disabled`) | See "Payout provider". `mock` refuses to start. |
| `OSUSU_MOCK_PAYMENTS_ENABLED` | must stay false | Refuses to start if true. |
| `DJANGO_STATIC_ROOT` | no (`backend/staticfiles`) | Where `collectstatic` writes; WhiteNoise serves it (Django admin CSS/JS). Must be writable by the deploy step, readable by the app. |
| `GUNICORN_BIND`, `GUNICORN_WORKERS`, `GUNICORN_TIMEOUT`, `GUNICORN_FORWARDED_ALLOW_IPS` | no | `gunicorn.conf.py`. Defaults: `127.0.0.1:8000`, 3, 30 s, `127.0.0.1` (the proxy). |
| `DB_*` | yes | PostgreSQL. Redis is **not** needed (only the paid assistant uses it, and it stays disabled). |

Frontend (Next.js): `NEXT_PUBLIC_API_URL` = the API's `https://` URL,
inlined at **build** time (build once per environment); `OSUSU_APP_ORIGIN`
= the app's own public `https://` origin, **required behind a proxy**
(otherwise every login/refresh/logout is refused with 403: `next start`
only knows its internal address). The refresh cookie is `Secure` when
`NODE_ENV=production`.

Dependencies: install from `requirements.lock` (hash-pinned, compiled with
pip-tools from `requirements.txt`; verified on Python 3.12.7 and 3.14.0):
`pip install --require-hashes -r requirements.lock`. To change a
dependency, edit `requirements.txt` and recompile:
`pip-compile --generate-hashes --strip-extras --no-emit-index-url --output-file requirements.lock requirements.txt`.
Frontend: `npm ci` (package-lock.json).

### Steps

In this order, with the new code and the environment loaded, **before**
the new app processes start:

```bash
pip install --require-hashes -r requirements.lock
python manage.py check --deploy        # expect only W005/W021 unless HSTS
                                       # subdomains/preload are opted into
python manage.py migrate --noinput
python manage.py createcachetable      # throttle counters; idempotent
python manage.py collectstatic --noinput
python manage.py report_ledger_anomalies
gunicorn -c gunicorn.conf.py config.wsgi   # via the process manager
```

Throttle counters live in PostgreSQL so every worker shares them. Without
`createcachetable` login and registration fail with 500 (closed, not
open). Without `collectstatic`, Django admin pages return 500 (the hashed
static manifest is missing); the JSON API is unaffected.

### Rollback

- Code: redeploy the previous build. Sprints 31-32 add no migrations; the
  throttle table and collected static files can stay.
- A rollback to a build before Sprint 31 brings back permissive CORS, no
  login throttling, no HTTPS enforcement **and a payout path that records
  mock payouts as PAID**. Do not roll back past Sprint 31 on an
  internet-facing deployment.
- HSTS cannot be rolled back for browsers that already received it.
- Never "fix" data by editing ledger rows (admin is read-only): use
  `report_ledger_anomalies` and a reviewed correction.

## Staging

**Status (2026-10-15): not deployed.** No hosting account, server, domain
or CI exists for this project. Everything below is configuration and a
procedure; it was rehearsed locally (see "Local rehearsal"), not deployed.

### Topology (one host)

```
browser --https--> Caddy :443 --http--> next start 127.0.0.1:3000   (staging.example.org)
                         \----http--> gunicorn  127.0.0.1:8000   (api.staging.example.org)
                                         |
                                     PostgreSQL (osusu_staging database only)
```

- Files: `deploy/staging.env.example` (backend), `deploy/frontend.staging.env.example`,
  `deploy/Caddyfile.staging`, `gunicorn.conf.py`. Copy the env templates to
  the host's secret store / env files (mode 600, outside the repo).
- **Private by default:** Caddy answers 404 outside `STAGING_ALLOWED_IPS`.
  Basic auth is unsuitable (the API uses the `Authorization` header). A VPN
  or private network is equally fine. Do not open it publicly without
  explicit approval.
- **Money is off:** `OSUSU_PAYOUT_PROVIDER=disabled` (execute -> 503, nothing
  recorded), `OSUSU_MOCK_PAYMENTS_ENABLED=false`; `mock` values refuse to
  start. Use test data only; never production data.
- **Proxy trust:** exactly one proxy (Caddy) on the same host:
  `DJANGO_TRUST_X_FORWARDED_PROTO=true`, `DJANGO_NUM_PROXIES=1`,
  `GUNICORN_FORWARDED_ALLOW_IPS=127.0.0.1`. Gunicorn binds to loopback, so
  nothing can reach it without passing through Caddy. Change all three
  together if the topology changes (e.g. a load balancer in front of Caddy
  adds one more trusted hop).

### Deployment checklist

1. Host: PostgreSQL (create `osusu_staging` + its own role), Python 3.12 or
   3.14, Node 20, Caddy 2. Firewall: only 80/443 open.
2. Secrets: generate a fresh `DJANGO_SECRET_KEY` (never reuse
   development's or production's) and DB password; store outside the repo.
3. Backend: `pip install --require-hashes -r requirements.lock`, then the
   steps under "Production deployment -> Steps" (check --deploy, migrate,
   createcachetable, collectstatic, report_ledger_anomalies).
4. Frontend: `npm ci`, then
   `NEXT_PUBLIC_API_URL=https://api.staging.example.org npm run build`;
   run `next start -H 127.0.0.1 -p 3000` with the frontend env file
   (`OSUSU_APP_ORIGIN` set).
5. Start gunicorn and Next.js under the process manager, then Caddy.
6. Smoke test (from an allowed address):
   - `https://api.../api/users/me/` -> 401; `http://...` -> redirect to https;
     `Strict-Transport-Security` present.
   - `https://api.../admin/login/` -> 200 and its CSS (`/static/admin/css/base.<hash>.css`) -> 200.
   - From a disallowed address -> 404.
   - CORS preflight from the app origin -> `Access-Control-Allow-Origin`; from another origin -> none.
7. Run `frontend/BROWSER_CHECKLIST.md` (staging variant) and record results.

### Rollback

- Keep the previous release directory, its virtualenv and its frontend
  build. Roll back = point the process manager at the previous release
  and restart gunicorn and Next.js; Caddy needs no change.
- Database: Sprints 31-32 add no migrations. For a release that does, take
  a `pg_dump` before `migrate` and only reverse a migration that is
  explicitly reversible and reviewed; never edit ledger rows.
- Do not roll back past Sprint 31 (see "Production deployment -> Rollback").
- Staging data is disposable: if in doubt, drop and recreate
  `osusu_staging` rather than repairing it.

### Local rehearsal (2026-10-15)

Production settings (`DJANGO_DEBUG=false`) against a local
`osusu_staging` database, gunicorn from a fresh `requirements.lock`
virtualenv, `next start` with a staging build, and a local TLS proxy that
behaves like Caddy (sets X-Forwarded-Proto, overwrites X-Forwarded-For,
passes Host). All Steps ran in order; the HTTP journey passed (see the
Sprint 32 report). It found one real defect, fixed: behind a proxy the
Next.js session routes refused every same-origin request (403), hence
`OSUSU_APP_ORIGIN`. A browser was not used.

## Refresh-token maintenance (SimpleJWT blacklist)

Every login records an `OutstandingToken`; every logout
(`POST /api/auth/logout/`) adds a `BlacklistedToken`. Neither table is
pruned automatically. Expired rows are useless (an expired token is
rejected anyway) and can be removed safely:

```bash
python manage.py flushexpiredtokens
```

It deletes only tokens whose `expires_at` has passed (refresh tokens live
1 day) together with their blacklist entries; live and revoked-but-unexpired
tokens are kept, so revocation keeps working.

Run it once a day from whatever scheduler the deployment already has, e.g.
cron on the application host:

```cron
15 3 * * *  cd /srv/osusu/backend && venv/bin/python manage.py flushexpiredtokens
```

No scheduler is part of this repository.

## Refresh-token rotation: deliberately off

`ROTATE_REFRESH_TOKENS` / `BLACKLIST_AFTER_ROTATION` are not enabled. Logout
revocation (blacklist) is enabled and verified.

### Why not now

With blacklist-after-rotation every refresh issues a new refresh token and
blacklists the one presented. The browser can legitimately present the same
cookie twice at nearly the same time:

- two tabs whose access tokens expire together;
- a page reload while an in-flight request is retrying a 401 (the
  in-tab single-flight in `lib/api/client.ts` does not span reloads or tabs);
- a slow network where the first refresh's Set-Cookie arrives after the
  second request was sent.

The first refresh wins and rotates; the second presents a blacklisted token,
gets 401, and the session route clears the cookie, logging the user out
although a valid successor exists. This race is pinned by
`frontend/tests/session-routes.test.ts` ("concurrent refreshes").

### Safe design (not implemented)

1. **Token family.** Add a `family` (random id) claim at login; every rotated
   successor keeps it. Persist per family: current jti, previous jti,
   rotated_at, and the successor token *encrypted at rest* (or a hash plus
   a server-side handle).
2. **Grace window for the previous token.** If the presented refresh token
   is the family's *previous* jti and `now - rotated_at <= 30 s`, return the
   *same* successor that was already issued (idempotent), not a new one and
   not 401. Both concurrent responses then set the same cookie value, so the
   cookie order no longer matters.
3. **Reuse detection.** A blacklisted jti presented *outside* the grace
   window (or any jti older than the previous one) means the token was
   stolen or replayed: blacklist the whole family (all descendants) and
   return 401. Audit it without logging token values.
4. **Serialise per family.** Do the lookup/rotation under
   `select_for_update` on the family row so two refreshes cannot both rotate.
5. **BFF.** No logic change needed: it already stores a rotated token when
   Django returns one, and clears the cookie only on 400/401. It must never
   log tokens (verified: none in server logs).
6. **Logout** blacklists the family, not just the presented jti.
7. **Tests before enabling:** concurrent refresh with the same token
   (both 200, same successor), replay after the grace window (family
   revoked), logout revokes successors, cookie update ordering in the BFF.

This needs a custom refresh view and a family model, i.e. its own reviewed
change; it is not a settings toggle.

## Payouts

Lifecycle and invariants: `finance.models.PayoutStatus`,
`finance.models.PayoutAttemptState` and `services/payouts/`. Design and
what is implemented: `docs/payout-uncertain-outcomes.md`.

The only path that marks a payout PAID is provider settlement evidence
applied through `PayoutAttemptService.record` ->
`PayoutCompletionService.complete` (attempt SUCCEEDED + exactly one PAYOUT
ledger row, de-duplicated by provider reference and by a database
constraint of one PAYOUT row per payout). No admin screen or command
changes a payout or attempt state; the PayoutAttempt admin is read-only.

### Payout attempts and uncertain outcomes (Sprint 33)

Every execution persists a `PayoutAttempt` (stable idempotency key
`osusu-payout-<payout id>-<attempt number>`) and commits it **before** the
provider is called; no transaction or row lock is held during the call.

- A timeout, connection loss, ambiguous error or unrecognised response is
  an **unknown** outcome: the payout is `processing`, its amount stays
  reserved (`reserved_for_payouts` in the treasury API), and execute answers
  409 `in_progress` without calling the provider. It is never "failed" and
  never retried blindly.
- Only the provider's definitive rejection, or a provider-proven "not sent",
  is a confirmed failure (`failed`, may be executed again with a new attempt
  and key).
- A crashed worker leaves a `prepared` attempt: treated exactly like
  unknown. After 15 minutes `PayoutResolutionService.resolve` marks it
  `unknown`.

**Resolving an unknown or stale attempt** (no provider is integrated, so no
automated resolution exists today):

1. `python manage.py report_payout_reconciliation` (read-only) lists it with
   its idempotency key and provider.
2. Confirm the outcome with the provider using that key / reference.
3. Do **not** execute the payout again, and do not edit rows. There is no
   operator command to record an outcome: one must be designed with
   two-person approval before any provider goes live.

Returns after PAID add one incoming `payout_return` ledger row (payout
`returned`); the original PAYOUT row is never edited. A returned payout
blocks new windows: paying the member again is a governance decision with
no tooling yet.

### Payout provider: live payouts are disabled

`OSUSU_PAYOUT_PROVIDER` selects the provider:

| Value | Where | Effect |
|---|---|---|
| `disabled` | default without `DJANGO_DEBUG` | Execute is refused before any write: HTTP 503 `{"result": "unavailable"}`; the payout stays APPROVED, no ledger row, no provider call. |
| `mock` | default with `DJANGO_DEBUG` | Development/tests only. Moves no money but records PAID. **Refused at startup without `DJANGO_DEBUG`.** |

Any other value refuses to start. No live provider is integrated, and
none has been selected or verified. The guards are layered:

1. Settings refuse `mock` (and `OSUSU_MOCK_PAYMENTS_ENABLED`) without DEBUG.
2. `get_payout_provider()` resolves only `mock`, only while
   `OSUSU_PAYOUT_MOCK_ALLOWED` (fixed from DEBUG at startup).
3. Outside development `ExecutePayoutService` sends only through a provider
   that declares `production_ready = True` and is not the mock, even if
   one is passed in directly.
4. `PayoutCompletionService` refuses a mock provider reference outside
   development.

A repeated execute of an already PAID payout still answers
`already_paid`, and of a `processing` payout `in_progress`, while payouts
are disabled.

#### Before a live provider may be enabled

All of these are open; none exists today.

- **Integration:** an adapter implementing the contract in
  `services/payouts/provider.py` (`send`, optional `lookup_status`,
  declared capabilities, `PayoutNotSent` only when provably not sent, a
  `PayoutEventVerifier` implementing the provider's official signature
  protocol), built against the provider's *documented* guarantees.
  Recipient bank details/KYC and the source account are not modelled yet.
- **Verified references:** the reference is stored as the PAYOUT row's
  `payment_reference` (unique across the ledger). It must be the provider's id,
  never one Osusu derives.
- **Ambiguous outcomes:** handled since Sprint 33 (unknown, reserved, not
  retried). Still missing: the provider's status lookup and its documented
  "not found" consistency guarantee, and a worker that runs
  `PayoutResolutionService` on a schedule.
- **Settlement and webhooks:** the state machine, event de-duplication and
  `PayoutEventService` exist; no HTTP endpoint or signature verifier does.
- **Reconciliation:** `PayoutReconciliationService` matches a provider
  settlement report against attempts and the ledger; fetching that report
  from a provider is not implemented, so the command runs local checks only.
- **Failure recovery:** an operator path to record a provider-confirmed
  outcome with two-person approval; a runbook for provider outages, unknown
  outcomes past the settlement window, returns and duplicate transfers.
- **Verification:** sandbox tests of every path above, then an independent
  review, before `production_ready = True` and a new
  `OSUSU_PAYOUT_PROVIDER` value are added.

### Payout HTTP API

`/api/circles/<id>/payout-windows/...` (see `frontend/API_CONTRACT.md`):
members vote, the creator opens, approves and executes. The views only call
`PayoutEngine`, `PayoutVoteService`, `PayoutApprovalService` and
`ExecutePayoutService`; every rule lives in those services.

## Ledger corrections

The ledger is append-only. A mistake is corrected with a new entry:

| Direction | Type | Effect |
|---|---|---|
| in  | `adjustment` | raises the balance |
| out | `adjustment_out` | lowers the balance |

Ledger rows are view-only in Django admin. Corrections are recorded only by `LedgerCorrectionService`, through the
`record_ledger_correction` command, by a user holding the
`finance.record_ledger_correction` permission (grant it in Django admin to
named operators only; circle creators do not have it). Each one stores the
reason, actor, the corrected ledger entry and/or an incident reference, and
an operator-chosen unique reference (`payment_reference =
correction:<reference>`): re-running the same correction is a no-op, reusing
a reference for a different one is refused. A `LEDGER_CORRECTION_RECORDED`
audit entry is written. Nothing is ever edited or deleted.

### 1. Read-only report

```bash
python manage.py report_ledger_anomalies            # human readable
python manage.py report_ledger_anomalies --json     # for the review record
python manage.py report_ledger_anomalies --circle <circle id>
```

Writes nothing. Findings:

- `payout_negative_amount`: PAYOUT row with amount < 0 (pre-Sprint 28 bug;
  each inflated the balance by 2 x |amount|)
- `non_positive_amount`: any other row with amount <= 0
- `payout_without_paid_payout`: PAYOUT row not tied to a PAID or RETURNED
  payout of its circle (`metadata.payout_id`)
- `paid_payout_without_ledger` / `paid_payout_multiple_ledger`: a PAID or
  RETURNED payout with no, or more than one, PAYOUT row

Payout attempts are reported separately and read-only by
`python manage.py report_payout_reconciliation [--json] [--circle <id>]`:
`attempt_outcome_unknown`, `attempt_prepared_stale`,
`attempt_submitted_overdue`, `payout_attempt_status_mismatch`,
`settled_attempt_ledger_mismatch`, `ledger_payout_without_settled_attempt`,
`returned_without_compensation`, `compensation_without_return`, and
`legacy_payout_without_attempt` (info: paid before Sprint 33). Provider-side
checks (`provider_transfer_unrecorded`, `provider_amount_mismatch`,
`provider_status_differs`, `provider_transfer_duplicated`,
`settled_attempt_missing_at_provider`) need a provider settlement report and
do not run yet.

### 2. Reviewed correction (one finding at a time)

For a `payout_negative_amount` row of `-X` (balance overstated by `2X`):

1. Save the `--json` report and get sign-off from the treasury owner.
2. Dry run (default; prints the balance before and after, writes nothing):

   ```bash
   python manage.py record_ledger_correction \
     --circle <circle id> --direction out --amount <2X> \
     --corrects-transaction <negative row id> \
     --reference reconcile-<negative row id> \
     --incident <ticket> --actor <operator username> \
     --reason "Pre-Sprint-28 negative payout row inflated the balance by 2X"
   ```

3. Check the printed balance change, then re-run with `--confirm`.
4. Re-run the report; the original row is still listed (it is never
   changed). Record the correction id against the finding.

Other findings need investigation first (e.g. a PAID payout without a
ledger row may mean money left without being recorded); correct only once
the true amount is known. Nothing reconciles automatically. The local
development database reported no anomalies (2026-10-10).
