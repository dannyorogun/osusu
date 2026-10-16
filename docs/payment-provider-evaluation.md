# Payment provider evaluation (Sprint 32, 2026-10-15)

**Status: research only. No provider has been contacted, selected, contracted
or integrated. Nothing here says any provider accepts Osusu's business
model.** That needs written confirmation from each provider after it has
reviewed the actual money flow, and legal advice on whether Osusu itself
needs FCA authorisation (see `regulatory-questions.md`).

Facts below come from the providers' public documentation as fetched on
2026-10-15 (links inline). Where the documentation did not answer a
question, it is listed under "Must confirm in writing" rather than guessed.

## The money flow being evaluated

1. Each member pays a fixed contribution each period (UK, GBP).
2. The pooled amount is held until a payout window is decided by member
   vote and quorum (existing governance rules).
3. The pool, or part of it, is paid to one member's bank account.
4. Refunds, reversals and failed payouts must be possible and traceable.

This is collecting money from many people and paying it to a different
person. Providers and regulators treat that very differently from a
merchant selling its own goods: it can look like **money remittance /
money transmission** (a regulated payment service under Schedule 1 of the
Payment Services Regulations 2017) or **holding client funds**. A standard
merchant acquiring account does not, by itself, authorise holding or
distributing funds between users.

## Candidates

### 1. Stripe Connect (separate charges and transfers)

- **Business model:** Stripe's Prohibited and Restricted Businesses list
  (updated 2026-09-22) lists **"Peer-to-peer money transmission" as
  prohibited**, and "Money transmitters, remittances, currency exchange
  services and other money service businesses" and "Crowdfunding
  platforms" as restricted.
  [stripe.com/en-gb/legal/restricted-businesses](https://stripe.com/en-gb/legal/restricted-businesses)
  A rotating savings circle may well be classified as P2P money transmission.
  **Highest risk of being refused.**
- **Flow:** charges land on the platform balance, transfers move funds to
  connected accounts (members would each need a connected account with
  identity verification). GB is a supported region; transfers must be used
  "only … in combination with the permitted use cases for charges".
  Refunds don't reverse transfers automatically, and the platform balance
  absorbs fees, refunds and chargebacks.
  [docs.stripe.com/connect/separate-charges-and-transfers](https://docs.stripe.com/connect/separate-charges-and-transfers)
  Holding funds safely before transfer ("funds segregation") is a
  **private preview** feature.
- **Idempotency:** `Idempotency-Key` on all POSTs. Retries return the saved
  response (including 500s) and differing parameters error. Keys may be
  pruned after 24 hours, after which a reused key creates a new request.
  [docs.stripe.com/api/idempotent_requests](https://docs.stripe.com/api/idempotent_requests)
- **Webhooks:** HMAC-SHA256 `Stripe-Signature` with timestamp; libraries
  default to a 5-minute tolerance against replay. Delivery can be duplicated
  and unordered (de-duplicate by event id). Live retries run for up to
  3 days. [docs.stripe.com/webhooks](https://docs.stripe.com/webhooks)
- **Card disputes** apply to card contributions and can claw back money
  after a payout has been made from the pool.

### 2. GoCardless (Direct Debit collection + Outbound Payments)

- **Collection:** Bacs Direct Debit suits fixed, recurring contributions.
  Direct Debits can be reversed by the payer under the Direct Debit
  Guarantee, so a contribution is never final. Exact time limits to be
  confirmed.
- **Outbound Payments:** UK/GBP via Faster Payments only. "The Outbound
  Payment API enforces idempotent creation to prevent duplicate payments.
  The Idempotency-Key header is mandatory." Confirmation of Payee results
  are reviewed and the payment approved before sending. API request
  signing is required.
  [docs.gocardless.com/docs/send-money](https://docs.gocardless.com/docs/send-money),
  [create an outbound payment](https://docs.gocardless.com/docs/send-money/send-an-outbound-payment/create-an-outbound-payment)
- **Statuses:** `verifying` → `pending_approval` → `scheduled` → `executing` →
  `executed` | `failed` | `cancelled`. Failed events carry a `cause`.
  [tracking outbound payments](https://docs.gocardless.com/docs/send-money/tracking-outbound-payments)
- **Business model:** the documentation does not say whether paying pooled
  member money to another member is permitted, or where the sending account's
  money is held. Must be confirmed.

### 3. TrueLayer (open-banking pay-ins + merchant account payouts)

- **Flow:** members pay by bank (open banking) into a TrueLayer-managed
  merchant account. Payouts go from that account: closed-loop (back to the
  account that paid) or open-loop (`external_account`, to an account that
  hasn't paid before). "It's not possible to make an open-loop payout unless
  you have an approved merchant account with sufficient funds."
  [payouts integration checklist](https://docs.truelayer.com/docs/payouts-integration-checklist),
  [payout basics](https://docs.truelayer.com/docs/payout-and-refund-basics)
- **Idempotency:** `Idempotency-Key` (UUID) is mandatory on payout requests.
  Retention period and conflict behaviour weren't in the pages read.
- **Statuses:** `pending` → `authorized` → `executed` | `failed`. Webhooks
  only fire for `executed`/`failed`. **A payout can move from `executed` to
  `failed` (returned by the beneficiary bank)**, so "executed" is not final.
  [payout webhooks](https://docs.truelayer.com/docs/payout-webhooks),
  [returns](https://docs.truelayer.com/docs/payout-and-refund-returns)
- **Webhooks:** `TL-Signature` (JWS, detached payload) +
  `X-TL-Webhook-Timestamp`. Must be verified.
- **Business model:** whether open-loop payouts of pooled member money to
  a different member are permitted needs TrueLayer's approval of the use
  case.

### 4. Modulr (e-money institution accounts + payouts)

- **Flow:** a Modulr account per circle (or a pooled account) receives
  contributions and sends Faster Payments. The API covers accounts,
  inbound/outbound payments, Confirmation of Payee and KYC/KYB onboarding.
- **Statuses:** `SUBMITTED`, `VALIDATED`, `PENDING_FOR_DATE`,
  `PENDING_FOR_FUNDS` → `PROCESSED` (final success) | `CANCELLED` |
  `ER_INVALID`/`ER_EXTSYS`/`ER_EXPIRED`/`ER_GENERAL` (final failures).
  `ER_EXTCONN` is "Issues with external system connectivity - will be
  retried by Modulr" (not final).
  [modulr.readme.io/docs/payment-statuses](https://modulr.readme.io/docs/payment-statuses)
- **Idempotency:** an optional `externalReference` (50 chars) is
  recommended. The pages read **do not say it prevents duplicate
  submission**, so a separate idempotency mechanism must be confirmed.
  [payments and transactions](https://modulr.readme.io/docs/payments-and-transactions)
- **Webhooks:** a `PAYOUT` webhook exists. Signing and retry details were
  not in the pages read.
- **Business model:** Modulr is an EMI, so funds held there are e-money
  and safeguarded by Modulr. Whether Osusu would be Modulr's client (with
  members as Osusu's customers) or members would be onboarded individually
  decides the regulatory position. To confirm.

Adyen for Platforms and Wise Platform are also plausible but were not
researched this sprint.

## Comparison (documentation only; not a selection)

| | Stripe Connect | GoCardless | TrueLayer | Modulr |
|---|---|---|---|---|
| Model explicitly allowed? | No, and P2P money transmission is **prohibited** | Not stated | Not stated (open-loop needs approval) | Not stated |
| Collect from many, pay one | Charges + transfers to connected accounts | DD collection + outbound | Pay-ins to merchant account + open-loop payout | Account receives + pays out |
| Recipient onboarding/KYC | Connected account per member | CoP on recipient | Beneficiary details; CoP to confirm | KYC/KYB API |
| Mandatory idempotency key | Yes (pruned after 24 h) | Yes (mandatory) | Yes (mandatory) | Not confirmed |
| Signed webhooks | HMAC + timestamp | Yes (details to read) | JWS + timestamp | Not confirmed |
| "Success" can later fail | Disputes, transfer reversals | DD indemnity claims | `executed` → `failed` (returns) | Returns (to confirm) |
| Sandbox | Yes | Yes | Yes | Yes (self-serve) |
| Pricing | Not researched; needs a quote | Not researched | Not researched | Not researched |

## Must confirm in writing (every candidate)

1. Do you accept a rotating savings circle (members pool fixed
   contributions; one member per period receives the pool, chosen by
   member vote)? Under which product and terms?
2. Who is the regulated entity holding the pooled funds between
   contribution and payout, and are they safeguarded? Is Osusu your
   customer, are the members, or both?
3. Do you require Osusu to hold its own FCA authorisation or registration,
   or can it operate as your agent / under your permissions?
4. Recipient onboarding: what KYC is required for contributors and for
   recipients, and who performs it?
5. Idempotency: header, retention period, behaviour on concurrent
   duplicate and on changed parameters.
6. For a timed-out payout request, which documented status enquiry
   gives a definitive answer, and how quickly?
7. The exact list of payout statuses, which are final, and whether a
   "successful" payout can later be returned or reversed (window and
   webhook).
8. Webhook signing scheme, retry schedule, duplicate/out-of-order delivery,
   and event replay or backfill after downtime.
9. Settlement/reconciliation reports (format, frequency, API access) with
   your transaction ids.
10. Contribution reversals: chargebacks or Direct Debit indemnity claims
    after the pool has been paid out. Who bears the loss?
11. Limits (per payment, daily), payout timing, cut-offs, and support SLAs.
12. Full pricing: pay-in, payout, CoP, onboarding, monthly minimums.

## Recommendation

Do not choose yet. Next step: get the legal/regulatory answers in
`regulatory-questions.md`, because they decide which provider model is even
possible. Then send questions 1–12 to at least GoCardless, TrueLayer and
Modulr (Stripe last, given its prohibited-business entry) and compare
their written answers against `payout-uncertain-outcomes.md`.
