import type { DecimalString, IsoDateTime, Uuid } from "./api";

/**
 * POST /api/payments/obligations/<obligation_id>/create/ 201.
 * Creating a payment only starts the provider flow; the obligation is
 * marked paid by the backend when the provider confirms (webhook).
 */
export type PaymentIntent = {
  id: Uuid;
  provider: string;
  provider_payment_id: string;
  amount: DecimalString;
  currency: string;
  status: string;
  checkout_url: string | null;
};

/** finance.models.ObligationStatus */
export type ObligationStatus = "pending" | "paid" | "overdue" | "waived";

/** GET /api/circles/<id>/obligations/ item - the requester's own only. */
export type Obligation = {
  id: Uuid;
  period_number: number;
  amount_due: DecimalString;
  due_date: IsoDateTime;
  status: ObligationStatus;
  paid_at: IsoDateTime | null;
};

/**
 * finance.models.PayoutStatus. Listed payouts are decided (approved,
 * processing, paid, failed or returned); pending/cancelled rows are
 * candidates and are never listed. "processing" means a payment attempt
 * may be moving money (submitted or outcome unknown): never "failed".
 */
export type PayoutStatus =
  | "pending"
  | "approved"
  | "processing"
  | "paid"
  | "failed"
  | "returned"
  | "cancelled";

/** finance.models.PayoutAttemptState of the latest attempt. */
export type PayoutAttemptState = "prepared" | "submitted" | "unknown" | "succeeded" | "failed" | "returned";

export type Payout = {
  id: Uuid;
  payout_window: number;
  amount: DecimalString;
  status: PayoutStatus;
  recipient: string;
  is_you: boolean;
  created_at: IsoDateTime;
  approved_at: IsoDateTime | null;
  paid_at: IsoDateTime | null;
  /** null before any payment attempt. */
  attempt_state: PayoutAttemptState | null;
};

/** GET /api/users/me/obligations/ item: own obligations, ACTIVE circles only. */
export type MyObligation = Obligation & { circle: { id: Uuid; name: string } };

/**
 * GET /api/circles/<id>/payouts/. `payouts` are decided (approved/paid);
 * `open_windows` have candidates but no approved recipient yet.
 * Votes and candidate identities are never returned.
 */
export type CirclePayouts = {
  payouts: Payout[];
  open_windows: Array<{ payout_window: number; candidate_count: number }>;
};

/** A candidate in a payout window: name only, never who voted for them. */
export type PayoutCandidate = {
  id: Uuid;
  display_name: string;
  is_you: boolean;
  status: PayoutStatus;
};

/**
 * GET /api/circles/<id>/payout-windows/<n>/. `can_*` are the backend's
 * hints for this user; every action is re-checked by Django.
 */
export type PayoutWindow = {
  payout_window: number;
  state: "open" | "approved" | "processing" | "paid" | "failed" | "returned" | "closed";
  candidates: PayoutCandidate[];
  /** Only while open: votes cast across the window and the quorum needed. */
  votes_cast: number | null;
  votes_required: number | null;
  /** The requester's own vote (a candidate id), if any. */
  your_vote: Uuid | null;
  payout: Payout | null;
  can_vote: boolean;
  can_approve: boolean;
  can_execute: boolean;
};

/** GET /api/circles/<id>/payout-windows/ */
export type CurrentPayoutWindow = { window: PayoutWindow | null; can_open_window: boolean };

/** Response of the window actions (open / vote / approve / execute). */
export type PayoutWindowActionResult = {
  window: PayoutWindow | null;
  /**
   * execute: paid / already_paid (200), submitted / unknown (202). Errors
   * carry failed (502, confirmed), in_progress (409), unavailable (503).
   */
  result?: "paid" | "already_paid" | "submitted" | "unknown";
};
