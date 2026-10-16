import type { DecimalString, IsoDateTime, Uuid } from "./api";

/** circles.models.CircleStatus */
export type CircleStatus =
  | "draft"
  | "recruiting"
  | "ready"
  | "locked"
  | "active"
  | "completed";

/** circles.serializers.CircleConstitutionSerializer */
export type CircleConstitution = {
  member_limit: number;
  contribution_amount: DecimalString;
  /** Free text on the backend (e.g. "weekly"); not an enum. */
  contribution_frequency: string;
  payout_amount: DecimalString;
  payout_frequency: string;
  cycle_length: number;
  quorum_percentage: number;
  grace_period_days: number;
  reserve_enabled: boolean;
  reserve_amount: DecimalString;
  allow_replacement_before_lock: boolean;
};

/**
 * circles.serializers.CircleSerializer - returned by
 * GET /api/circles/<id>/ and POST /api/circles/.
 * Member counts, members and finances are NOT part of this response.
 */
export type Circle = {
  id: Uuid;
  name: string;
  description: string;
  status: CircleStatus;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  financial_locked_at: IsoDateTime | null;
  /** Always created with the circle; null only for legacy rows. */
  constitution: CircleConstitution | null;
};

/**
 * POST /api/circles/ request (circles.serializers.CreateCircleSerializer).
 * Decimal fields are sent as strings to avoid float rounding.
 */
export type CreateCircleRequest = {
  name: string;
  description?: string;
  member_limit: number;
  contribution_amount: DecimalString;
  payout_amount: DecimalString;
  contribution_frequency?: string;
  payout_frequency?: string;
  cycle_length: number;
  quorum_percentage: number;
  grace_period_days: number;
  reserve_enabled?: boolean;
  reserve_amount: DecimalString;
  allow_replacement_before_lock?: boolean;
};

/** POST /api/circles/invitations/<token>/accept/ 200 response. */
export type AcceptInvitationResponse = {
  accepted: true;
  circle_id: Uuid;
  membership_id: Uuid;
  status: string;
};

/** GET /api/circles/ item: circles where the requester is an ACTIVE member. */
export type MyCircle = {
  id: Uuid;
  name: string;
  description: string;
  status: CircleStatus;
  created_at: IsoDateTime;
  /** ACTIVE memberships only, counted by the backend. */
  member_count: number;
  constitution: Pick<
    CircleConstitution,
    | "member_limit"
    | "contribution_amount"
    | "contribution_frequency"
    | "payout_amount"
    | "payout_frequency"
    | "cycle_length"
  > | null;
};

/** circles.models.MembershipStatus; the member list shows active + invited. */
export type MembershipStatus = "invited" | "active" | "left" | "removed";

/** GET /api/circles/<id>/members/ item. No email or user id by design. */
export type CircleMember = {
  /** Membership id. */
  id: Uuid;
  display_name: string;
  username: string;
  status: MembershipStatus;
  joined_at: IsoDateTime | null;
  constitution_accepted: boolean;
  constitution_accepted_at: IsoDateTime | null;
  is_creator: boolean;
  is_you: boolean;
};

/** finance.models.TransactionType */
export type LedgerTransactionType =
  | "contribution"
  | "payout"
  | "refund"
  | "reserve"
  | "adjustment"
  | "adjustment_out"
  | "payout_return";

/**
 * GET /api/circles/<id>/treasury/ - from COMPLETED ledger rows only.
 * Pending/failed rows are counted but never included in any amount.
 */
export type TreasurySummary = {
  balance: DecimalString;
  /** Payouts whose money may be moving: in the balance, but not available. */
  reserved_for_payouts: DecimalString;
  available_balance: DecimalString;
  completed_transaction_count: number;
  totals: Record<LedgerTransactionType, { total: DecimalString; count: number }>;
  pending_transaction_count: number;
  failed_transaction_count: number;
};

export type ActivityEventType =
  | "circle_created"
  | "circle_ready"
  | "circle_locked"
  | "invitation_sent"
  | "member_joined"
  | "constitution_accepted"
  | "payout_window_opened"
  | "payout_approved"
  | "payout_completed"
  | "restructure_proposed";

/** GET /api/circles/<id>/activity/ item (newest first, at most 50). */
export type ActivityEvent = {
  id: Uuid;
  event: ActivityEventType;
  occurred_at: IsoDateTime;
  /** Display name of the member involved; null if unknown/deleted. */
  member: string | null;
  payout_window: number | null;
};

/** POST /api/circles/<id>/invite/ 201 - the code must be shared by the inviter. */
export type InvitationCreated = {
  invited: true;
  invitation_id: Uuid;
  email: string;
  expires_at: IsoDateTime;
  token: string;
};

/** POST /api/circles/<id>/accept-constitution/ 200 */
export type ConstitutionAccepted = {
  accepted: true;
  circle_id: Uuid;
  membership_id: Uuid;
  accepted_at: IsoDateTime;
};

/**
 * POST /api/circles/<id>/evaluate/ 200 (creator only). A passing
 * evaluation moves the circle to "ready". Only the check booleans are
 * shown; amounts in this response are not used by the frontend.
 */
export type FormationEvaluation = {
  ready: boolean;
  formation_checks: Record<string, boolean>;
  financial_checks: { passed: boolean; checks: Record<string, boolean> } | null;
  cash_flow?: { passed: boolean; failures: unknown[] } | null;
};

/** POST /api/circles/<id>/lock/ 200; 400 bodies carry `checks`. */
export type FinancialLockResult = { locked: true; circle: Circle };

/** GET /api/circles/<id>/trust/ - factual counts only; never a score. */
export type TrustSummary = {
  data_status: "available" | "insufficient_data";
  your_record_in_circle: {
    total: number;
    pending: number;
    paid: number;
    overdue: number;
    waived: number;
  };
  your_history: {
    completed_circles: number;
    paid_contributions: number;
    overdue_contributions: number;
  };
  circle: { active_members: number; invitation_connections: number };
  score: null;
  score_unavailable_reasons: string[];
};
