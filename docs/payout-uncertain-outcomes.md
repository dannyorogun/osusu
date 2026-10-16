# Design: payout requests with uncertain outcomes

**Status: provider-independent foundation implemented (Sprint 33); no
provider integrated.** Live payouts stay disabled
(`OSUSU_PAYOUT_PROVIDER=disabled`) until a provider is chosen, an adapter
is built against that provider's *documented* guarantees, sandbox-tested
and independently reviewed. **No-go for real money.** See
"Sprint 33: what was built" at the end; the sections below are the
Sprint 32 design, kept for reference.

## The problem with the pre-Sprint 33 code

`ExecutePayoutService` (services/payouts/execute_payout_service.py) calls
`provider.send()` inside the row lock and treats **any exception as
FAILED (retryable)**. With real money that is wrong. A timeout, connection
reset or 5xx after the request left Osusu does not prove the provider
didn't send money. "FAILED, retry" could pay twice whenever the provider
doesn't de-duplicate on our key. The mock hides this because it can't fail
ambiguously.

Rule: **a payout is only marked failed, or retried, on the provider's
definitive answer, or where the provider's written idempotency guarantee
makes a blind retry provably safe.**

## Outcomes to distinguish

| # | Outcome | How we know | Money moved? | Ledger |
|---|---|---|---|---|
| 1 | **Request not sent** | Failure before bytes left (DNS, connect refused, local validation), recorded before dispatch | No | none |
| 2 | **Provider confirmed success** | Synchronous 2xx with provider id and an accepted status | Committed, not yet settled | none yet (funds reserved) |
| 3 | **Provider confirmed failure** | Definitive rejection (4xx validation, documented final failure status) | No | none |
| 4 | **Outcome unknown** | Timeout / reset / 5xx / unparseable response **after dispatch** | Maybe | none (funds reserved) |
| 5 | **Settlement pending** | Provider says accepted/executing (e.g. `executing`, `authorized`, `PENDING_*`) | In flight | none (funds reserved) |
| 6 | **Settlement confirmed** | Provider's final success (`executed` / `PROCESSED`), by signed webhook or status enquiry | Yes | **one PAYOUT row** |
| 7 | **Reversal / return** | Provider reports return after success (e.g. TrueLayer `executed`→`failed`), or an operator-initiated recall | Came back | **new** compensating incoming row; the PAYOUT row is never edited |

## Data model (proposed)

`Payout.status` gains states. Existing values keep their meaning:

```
APPROVED ──► SUBMITTING ──► SUBMITTED ──► PAID
   ▲             │   │           │  ▲       │
   │             │   │           ▼  │       ▼
   │             │   └──► OUTCOME_UNKNOWN   RETURNED
   │             ▼           │
   └──── NOT_SENT /          ▼
         REJECTED ◄──── (enquiry: not found / rejected)
```

- `SUBMITTING`: an attempt row is persisted and committed **before** the
  provider call.
- `SUBMITTED`: the provider acknowledged, provider reference stored;
  settlement pending.
- `OUTCOME_UNKNOWN`: dispatched, no definitive answer. **Never retried
  blindly.**
- `PAID`: settlement confirmed; exactly one PAYOUT ledger row.
- `REJECTED` / `NOT_SENT`: definitive no-money outcomes; may be re-executed.
  This replaces today's "FAILED (retryable)".
- `RETURNED`: money came back after PAID.

New table **`PayoutAttempt`** (append-only, one row per dispatch):

| field | purpose |
|---|---|
| `payout` FK, `attempt_number` | unique together |
| `idempotency_key` | see below; unique |
| `state` | `created` → `dispatched` → `accepted` / `rejected` / `unknown` |
| `provider`, `provider_reference` | provider-issued id; unique per provider when present |
| `request_hash` | hash of the exact amount/recipient/currency sent |
| `provider_status`, `provider_status_at` | last status seen |
| `created_at`, `dispatched_at`, `resolved_at` | timeline |
| `error_class` | e.g. `timeout`, `http_503`, `validation` (no secrets, no bodies) |

New table **`ProviderEvent`** (append-only): `provider`, `event_id` (unique
together), `event_type`, `received_at`, `signature_verified_at`,
`provider_reference`, `processed_at`, `payload_digest`. Raw payloads, if
stored at all, live encrypted with limited retention.

## Idempotency keys

- **Stable per instruction:** `osusu-payout-{payout.id}-{instruction}`,
  where `instruction` changes only when what we're asking for changes
  (recipient bank details or amount). Every retry of the same instruction
  reuses the same key, so a provider that honours keys returns the
  original transfer, never a new one.
- **Persisted before dispatch** in `PayoutAttempt` (committed in its own
  transaction), so a crash between "sent" and "recorded" leaves a record
  that we may have sent.
- The provider's documented key retention matters. Stripe API v1 may prune
  keys after 24 hours, after which the same key makes a *new* request. A
  retry is only safe inside the provider's documented window **and** with
  identical parameters (`request_hash`). Outside that window, resolve by
  enquiry instead.

## Execution flow

1. **Lock and reserve** (transaction A, `select_for_update` on the payout as
   today). Check status is APPROVED/REJECTED/NOT_SENT, governance (quorum,
   approval) and that `treasury_balance − reserved_outflows ≥ amount`, where
   reserved = amounts of payouts in SUBMITTING, SUBMITTED or
   OUTCOME_UNKNOWN. Create a `PayoutAttempt(state=created)`, set the payout
   to `SUBMITTING`, commit. **The provider is not called inside a database
   transaction or row lock**; this removes today's lock-held-during-network-call
   trade-off. Concurrent executions are still serialised because the second
   one finds `SUBMITTING` and stops.
2. **Dispatch** with the key and a short client timeout. Mark the attempt
   `dispatched` before writing to the socket, as far as the HTTP client
   allows. Any doubt counts as dispatched.
3. **Classify** the response (transaction B):
   - 2xx with a provider id and an accepted status → attempt `accepted`,
     payout `SUBMITTED`, store `provider_reference`.
   - Documented definitive rejection → attempt `rejected`, payout `REJECTED`.
     Funds unreserved; re-execution allowed (same key if the provider's
     rules say so).
   - Failure **before** dispatch → attempt `rejected` with
     `error_class=not_sent`, payout `NOT_SENT`.
   - Anything else (timeout, reset, 5xx, unparseable, 409 "in progress")
     → attempt `unknown`, payout `OUTCOME_UNKNOWN`. Funds stay reserved,
     the window stays unresolved (new windows are already blocked), and
     the UI says "payment status being confirmed", never "failed".
4. **Resolve unknowns** by status enquiry, never by blind resend:
   - Query the provider by idempotency key or our reference, if the provider
     documents that, and otherwise by the provider id from a later webhook.
     Use backoff (e.g. 1, 5, 15, 60 minutes, then hourly).
   - Found and accepted → `SUBMITTED`. Found and failed → `REJECTED`.
     **Not found** only counts as "not sent" if the provider's documentation
     guarantees enquiries are consistent after N minutes. Otherwise keep
     waiting.
   - Still unknown after the documented settlement window → escalate to
     manual recovery (below). Never auto-resend.
   - A resend with the **same key and identical parameters** is allowed
     only if the provider documents that this returns the original transfer
     or re-executes nothing.
5. **Settlement** (signed webhook or enquiry): the documented final success
   status → in one transaction, append the single PAYOUT ledger row
   (`payment_reference = provider_reference`, unique) via
   `PayoutCompletionService`, set payout `PAID`, release the reservation,
   and audit. A documented final failure after `SUBMITTED` → `REJECTED`,
   no ledger row.
6. **Return after PAID** → payout `RETURNED`; append a new **incoming**
   ledger row (a dedicated `payout_return` type or a reviewed
   `adjustment`), referencing the PAYOUT row and the provider event.
   Treasury and member records are restored by addition, never by edit.
   Whether the member is paid again is a new governance decision, not an
   automatic retry.

## Webhooks

- **Verify the signature on the raw body before parsing**, using the
  provider's scheme (e.g. Stripe `Stripe-Signature` HMAC-SHA256 with
  timestamp; TrueLayer `TL-Signature` JWS with `X-TL-Webhook-Timestamp`).
  Reject a stale timestamp (Stripe's libraries default to a 5-minute
  tolerance). Compare in constant time. Allow two secrets during rotation.
- **Replay and duplicates:** insert `ProviderEvent(provider, event_id)`
  first, under its unique constraint. A duplicate is acknowledged (2xx)
  and ignored. Events arrive out of order (documented by Stripe), so state
  changes go through the payout state machine, which ignores transitions
  that move backwards (e.g. a late "pending" after "executed").
- **Acknowledge quickly**, process asynchronously. Process the event
  idempotently against `provider_reference`.
- Webhooks are a hint, not the only source: the enquiry job also confirms
  `SUBMITTED` payouts, because webhook delivery stops after the provider's
  retry period (Stripe live: up to 3 days).
- Follows the existing `payments` webhook pattern (signed, de-duplicated
  `WebhookEvent`) for contributions.

## No duplicate ledger effects

- Exactly one PAYOUT row per payout: written only on settlement, with
  `payment_reference = provider_reference` (already unique on
  `LedgerTransaction`), inside the same transaction that moves the payout
  to PAID under `select_for_update`. `LedgerService` already returns the
  existing row for a repeated reference.
- No ledger row on submission, unknown or rejection. Funds are reserved in
  payout state, so the treasury guard can't double-allocate them.
- Returns add rows and never modify them. `report_ledger_anomalies` gains
  checks: PAID without exactly one PAYOUT row (exists),
  SUBMITTED/OUTCOME_UNKNOWN older than the settlement window, attempts with
  more than one distinct provider reference, and provider references not
  seen in settlement reports.

## Reconciliation

Daily job, read-only, its output reviewed by the treasury owner:

1. Fetch the provider's settlement / transaction report for the previous
   day(s), from the API if available.
2. Match on provider reference: our PAID payouts ↔ provider executed
   transfers (amount, currency, recipient), our contributions ↔ pay-ins.
3. Report: provider transfers with no Osusu record (critical: money
   moved that we didn't record), Osusu PAID with no provider transfer,
   amount mismatches, returns not yet recorded, and unknown attempts older
   than the threshold.
4. Corrections only through the existing reviewed process
   (`record_ledger_correction`, dry run, then treasury-owner sign-off).

## Manual recovery and audit

- Every state change writes an `AuditLog` entry with actor (system job or
  named operator), attempt id, provider reference and reason. No secrets,
  no bank details.
- An operator view lists OUTCOME_UNKNOWN, overdue SUBMITTED and RETURNED
  payouts. Operator actions are limited to: trigger an enquiry, record a
  provider-confirmed outcome (with the provider's evidence id), or escalate.
  An operator **cannot** mark a payout PAID or REJECTED without a provider
  reference or written provider confirmation, and two-person approval
  (operator + treasury owner) is required for any manual resolution.
- Runbook: provider outage, an unknown older than the settlement window,
  a return after PAID, a duplicate transfer found by reconciliation
  (recall request to the provider, then a reviewed correction), and key
  rotation.

## Tests required before enabling

Sandbox tests for every row of the outcome table, including injected
timeouts after dispatch, duplicate and out-of-order webhooks, a forged or
stale signature, a return after PAID, concurrent executions and enquiries,
and a crash between dispatch and the classification commit. Plus the
existing invariants (quorum, approval, idempotent completion, positive
ledger amounts).

## Sprint 33: what was built, and where it differs from the design above

Built (backend/finance/models.py, backend/services/payouts/):

- `PayoutAttempt` (append-only, never deleted, PROTECT) with
  `PayoutAttemptState`: `prepared` → `submitted` | `unknown` | `succeeded`
  | `failed`; `submitted` → `succeeded` | `failed`; `unknown` →
  `submitted` | `succeeded` | `failed`; `succeeded` → `returned`.
  `failed` and `returned` are final. Any other change raises
  `PayoutAttemptTransitionError`.
- Database constraints: one attempt per (payout, number); **at most one
  non-failed attempt per payout**; unique idempotency key; unique (provider,
  provider reference); **one PAYOUT and one PAYOUT_RETURN ledger row per
  payout** (expression index on `metadata->>'payout_id'`).
- `ExecutePayoutService`: prepare (durable transaction, row lock) → send
  (no transaction, no lock) → record (durable transaction). Uses
  `transaction.atomic(durable=True)`, so calling it inside an outer
  transaction raises instead of silently holding the transaction open.
- Provider contract (`services/payouts/provider.py`) with capabilities
  that default to the safe value, `PayoutNotSent`, classification,
  `VerifiedPayoutEvent`, a `PayoutEventVerifier` base that refuses
  everything, and `ProviderTransferRecord`.
- `PayoutEventService` (verified events, de-duplicated through the existing
  `WebhookEvent` table, identifiers only), `PayoutResolutionService`
  (status lookup when a provider declares it; stale `prepared` →
  `unknown`), `PayoutReturnService` (compensating incoming
  `payout_return` row), `PayoutReconciliationService` and the read-only
  `report_payout_reconciliation` command.
- Reservation: `TreasuryEngine.reserved_for_payouts` (sum of `processing`
  payouts) and `available_balance`, used by execute and `TreasuryGuard`
  and returned by the treasury API.

Deliberate differences from the design above:

| Design | Implemented | Why |
|---|---|---|
| Payout states SUBMITTING, SUBMITTED, OUTCOME_UNKNOWN, NOT_SENT, REJECTED | One payout state `processing`; detail lives on the attempt. `failed` kept, meaning *confirmed* failure (covers NOT_SENT/REJECTED) | Avoids two overlapping status fields; the payout status is always derived from the latest attempt in the same transaction |
| Attempt states created → dispatched → accepted/rejected/unknown | prepared → submitted/unknown → succeeded/failed → returned | Settlement and returns belong to the attempt; "dispatched" cannot be observed reliably, so `prepared` is treated as possibly sent |
| Key per instruction, reused across retries | Key per attempt (`osusu-payout-<id>-<n>`) | A new attempt exists only after a *confirmed* failure, and some providers return the cached failure for a reused key. Recipient instructions are not modelled, so "instruction" has no other meaning yet |
| New `ProviderEvent` table, unique (provider, event id) | Reuses `payments.WebhookEvent` (event id unique on its own) with an identifiers-only payload | Avoids a duplicate model. **Limitation:** two providers using the same event id would collide (the second is refused, not misapplied) |
| `payment_reference` uniqueness alone guards PAYOUT rows | Also a per-payout unique constraint | A second, different reference for the same payout can no longer create a second row |
| Operator can record a provider-confirmed outcome with two-person approval | Not built | Needs a reviewed approval design; until then an unknown outcome stays unresolved and reserved |
| Returned payout | Blocks new windows; the member is not re-selected automatically | Paying again is a governance decision that has no tooling yet |

Assumptions (to replace with the chosen provider's documented values):
a stale `prepared` attempt after 15 minutes; `submitted` overdue after 3
days; returns are of the full amount (partial returns need a reviewed
ledger correction). The development mock declares synchronous settlement
so the local journey reaches PAID; that proves nothing about any real
provider.

Still unsafe for real money: no provider adapter, signature verifier,
webhook endpoint, status lookup, settlement-report fetch, scheduled
resolution worker, operator resolution path, recipient bank details/KYC,
source-account model, or regulatory answers (`regulatory-questions.md`).
