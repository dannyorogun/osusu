import type { ActivityEvent, CircleMember } from "@/types/circle";
import type { Obligation, Payout } from "@/types/payment";

type Tone = "neutral" | "brand" | "success" | "warning" | "danger" | "info";

/** Display labels only; statuses are decided by the backend. */
export const OBLIGATION_STATUS: Record<Obligation["status"], { label: string; tone: Tone }> = {
  pending: { label: "Due", tone: "info" },
  paid: { label: "Paid", tone: "success" },
  overdue: { label: "Overdue", tone: "danger" },
  waived: { label: "Waived", tone: "neutral" },
};

export const PAYOUT_STATUS: Record<Payout["status"], { label: string; tone: Tone }> = {
  pending: { label: "Pending", tone: "neutral" },
  approved: { label: "Approved, not yet paid", tone: "warning" },
  processing: { label: "Payment being confirmed", tone: "warning" },
  paid: { label: "Paid", tone: "success" },
  failed: { label: "Payment failed, not paid", tone: "danger" },
  returned: { label: "Payment returned, not paid", tone: "danger" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

export const MEMBER_STATUS: Record<CircleMember["status"], { label: string; tone: Tone }> = {
  active: { label: "Active", tone: "success" },
  invited: { label: "Invited", tone: "info" },
  left: { label: "Left", tone: "neutral" },
  removed: { label: "Removed", tone: "neutral" },
};

export function describeActivity(event: ActivityEvent): string {
  const who = event.member ?? "A member";
  const window = event.payout_window === null ? "" : ` ${event.payout_window}`;
  switch (event.event) {
    case "circle_created":
      return `${who} created the circle`;
    case "circle_ready":
      return "The circle passed its formation checks";
    case "circle_locked":
      return `${who} financially locked the circle`;
    case "invitation_sent":
      return `${who} sent an invitation`;
    case "member_joined":
      return `${who} joined the circle`;
    case "constitution_accepted":
      return `${who} accepted the constitution`;
    case "payout_window_opened":
      return `Payout window${window} opened`;
    case "payout_approved":
      return `Payout window${window} approved for ${who}`;
    case "payout_completed":
      return `Payout window${window} paid to ${who}`;
    case "restructure_proposed":
      return `${who} proposed a restructure`;
    default:
      return "Circle activity";
  }
}

/** Readable names for the backend's check keys; unknown keys are humanized. */
export const CHECK_LABELS: Record<string, string> = {
  constitution_exists: "Constitution recorded",
  minimum_members: "At least 2 active members",
  member_limit: "Within the member limit",
  constitution_accepted: "Every active member accepted the constitution",
  contribution_valid: "Contribution amount is positive",
  payout_valid: "Payout amount is positive",
  cycle_length_valid: "Cycle is long enough for every member",
  quorum_valid: "Quorum is between 1% and 100%",
  reserve_valid: "Reserve is valid",
  members_exist: "At least 2 active members",
  contribution_positive: "Contribution amount is positive",
  payout_positive: "Payout amount is positive",
  cycle_length_positive: "Cycle length is positive",
  payout_frequency_supported: "Payout frequency is supported",
  payout_frequency_fits_cycle: "Payout frequency fits the cycle",
  one_payout_per_member: "One payout per member",
  contributions_cover_obligations: "Contributions cover payouts and reserve",
  payout_matches_cycle: "Payout matches the contributions collected",
  cash_flow_valid: "Treasury never runs short during the cycle",
  circle_ready: "Circle has passed formation (status Ready)",
  formation_valid: "Formation checks pass",
  financial_integrity: "Financial integrity checks pass",
};
