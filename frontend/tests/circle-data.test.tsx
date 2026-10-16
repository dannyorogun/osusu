import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CircleDetailPage from "@/app/(app)/circles/[circleId]/page";
import DashboardPage from "@/app/(app)/dashboard/page";
import {
  ActivitySection,
  MembersSection,
  ObligationsSection,
  PayoutsSection,
  TreasurySection,
} from "@/components/circles/CircleDataSections";
import { MyCircles } from "@/components/circles/MyCircles";
import { MyPayments } from "@/components/money/MyPayments";
import { MyPayouts } from "@/components/money/MyPayouts";
import { osusu } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/errors";
import type {
  ActivityEvent,
  Circle,
  CircleMember,
  MyCircle,
  TreasurySummary,
} from "@/types/circle";
import type { CirclePayouts, MyObligation, Obligation } from "@/types/payment";

import { CIRCLE, USER } from "./helpers";
import { navigation } from "./router";

vi.mock("@/lib/api/endpoints", () => ({
  osusu: {
    circles: {
      list: vi.fn(), get: vi.fn(), members: vi.fn(), obligations: vi.fn(),
      payouts: vi.fn(), treasury: vi.fn(), activity: vi.fn(), trust: vi.fn(),
    },
    users: { obligations: vi.fn() },
    assistant: { ask: vi.fn() },
    payoutWindows: { current: vi.fn().mockResolvedValue({ window: null, can_open_window: false }) },
  },
}));

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ currentUser: USER }),
}));

const api = vi.mocked(osusu.circles);
const users = vi.mocked(osusu.users);
const ID = CIRCLE.id;

const MY_CIRCLE: MyCircle = {
  id: ID,
  name: "Manchester Developers",
  description: "",
  status: "active",
  created_at: "2026-09-02T09:30:00Z",
  member_count: 3,
  constitution: {
    member_limit: 5,
    contribution_amount: "50.00",
    contribution_frequency: "weekly",
    payout_amount: "100.00",
    payout_frequency: "biweekly",
    cycle_length: 2,
  },
};
const OTHER_CIRCLE: MyCircle = {
  ...MY_CIRCLE,
  id: "5e1d2c3b-0000-4000-8000-000000000002",
  name: "Leeds Savers",
  status: "recruiting",
};

const MEMBERS: CircleMember[] = [
  {
    id: "m1", display_name: "Ada Obi", username: "ada", status: "active",
    joined_at: "2026-09-02T09:30:00Z", constitution_accepted: true,
    constitution_accepted_at: "2026-09-03T09:30:00Z", is_creator: true, is_you: true,
  },
  {
    id: "m2", display_name: "Bola", username: "bola", status: "invited",
    joined_at: null, constitution_accepted: false, constitution_accepted_at: null,
    is_creator: false, is_you: false,
  },
];

const OBLIGATIONS: Obligation[] = [
  {
    id: "o1", period_number: 1, amount_due: "50.00", due_date: "2026-10-01T00:00:00Z",
    status: "paid", paid_at: "2026-09-30T12:00:00Z",
  },
  {
    id: "o2", period_number: 2, amount_due: "50.10", due_date: "2026-10-15T00:00:00Z",
    status: "overdue", paid_at: null,
  },
];

const MY_OBLIGATIONS: MyObligation[] = OBLIGATIONS.map((o) => ({
  ...o,
  circle: { id: ID, name: "Manchester Developers" },
}));

const PAYOUTS: CirclePayouts = {
  payouts: [
    {
      id: "p2", payout_window: 2, amount: "200.00", status: "approved", recipient: "Bola",
      is_you: false, created_at: "2026-10-05T00:00:00Z", approved_at: "2026-10-06T00:00:00Z",
      paid_at: null, attempt_state: null,
    },
    {
      id: "p1", payout_window: 1, amount: "200.00", status: "paid", recipient: "Ada Obi",
      is_you: true, created_at: "2026-09-20T00:00:00Z", approved_at: "2026-09-21T00:00:00Z",
      paid_at: "2026-09-22T00:00:00Z", attempt_state: "succeeded",
    },
  ],
  open_windows: [{ payout_window: 3, candidate_count: 2 }],
};

const TREASURY: TreasurySummary = {
  balance: "30.05",
  completed_transaction_count: 4,
  totals: {
    contribution: { total: "100.10", count: 2 },
    payout: { total: "60.00", count: 1 },
    refund: { total: "10.05", count: 1 },
    reserve: { total: "0.00", count: 0 },
    adjustment: { total: "0.00", count: 0 },
    adjustment_out: { total: "0.00", count: 0 },
    payout_return: { total: "0.00", count: 0 },
  },
  reserved_for_payouts: "0.00",
  available_balance: "30.05",
  pending_transaction_count: 2,
  failed_transaction_count: 1,
};

const ACTIVITY: ActivityEvent[] = [
  {
    id: "a2", event: "payout_completed", occurred_at: "2026-09-22T00:00:00Z",
    member: "Ada Obi", payout_window: 1,
  },
  {
    id: "a1", event: "circle_created", occurred_at: "2026-09-02T09:30:00Z",
    member: "Ada Obi", payout_window: null,
  },
];

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  users.obligations.mockReset();
});

describe("My circles", () => {
  it("loads and links to each circle", async () => {
    api.list.mockResolvedValue([MY_CIRCLE]);
    render(<MyCircles />);

    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
    const link = await screen.findByRole("link", { name: /Manchester Developers/ });
    expect(link).toHaveAttribute("href", `/circles/${ID}`);
    expect(link).toHaveTextContent("3 of 5 members");
  });

  it("shows an empty state with a create action", async () => {
    api.list.mockResolvedValue([]);
    render(<MyCircles />);
    expect(await screen.findByText("You haven't joined a circle yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create a circle" })).toHaveAttribute("href", "/circles/new");
  });

  it("shows an error with retry", async () => {
    api.list.mockRejectedValueOnce(new ApiError(500)).mockResolvedValueOnce([MY_CIRCLE]);
    render(<MyCircles />);

    expect(await screen.findByRole("alert")).toHaveTextContent("We couldn't load your circles");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: /Manchester Developers/ })).toBeInTheDocument();
  });
});

describe("circle sections", () => {
  it("members: shows names and statuses, never emails", async () => {
    api.members.mockResolvedValue(MEMBERS);
    const { container } = render(<MembersSection circleId={ID} />);

    expect(await screen.findByText("Ada Obi")).toBeInTheDocument();
    expect(screen.getByText(/\(you\)/)).toBeInTheDocument();
    expect(screen.getByText("Invited")).toBeInTheDocument();
    expect(screen.getByText("Not yet accepted")).toBeInTheDocument();
    expect(container).not.toHaveTextContent("@");
  });

  it("obligations: amounts and statuses exactly as returned", async () => {
    api.obligations.mockResolvedValue(OBLIGATIONS);
    render(<ObligationsSection circleId={ID} />);

    const table = await screen.findByRole("table");
    expect(within(table).getByText("£50.10")).toBeInTheDocument();
    expect(within(table).getByText("Overdue")).toBeInTheDocument();
    expect(within(table).getByText("Paid")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /pay/i })).not.toBeInTheDocument();
  });

  it("obligations: empty state", async () => {
    api.obligations.mockResolvedValue([]);
    render(<ObligationsSection circleId={ID} />);
    expect(await screen.findByText("No contributions due yet")).toBeInTheDocument();
  });

  it("payouts: decided payouts and open windows, approved is not shown as paid", async () => {
    api.payouts.mockResolvedValue(PAYOUTS);
    render(<PayoutsSection circleId={ID} />);

    expect(await screen.findByText("Approved, not yet paid")).toBeInTheDocument();
    expect(screen.getByText("Ada Obi (you)")).toBeInTheDocument();
    expect(await screen.findByText("No payout window has been opened yet.")).toBeInTheDocument();
  });

  it("payouts: empty state", async () => {
    api.payouts.mockResolvedValue({ payouts: [], open_windows: [] });
    render(<PayoutsSection circleId={ID} />);
    expect(await screen.findByText("No payouts yet")).toBeInTheDocument();
  });

  it("treasury: shows the backend balance and excluded transactions", async () => {
    api.treasury.mockResolvedValue(TREASURY);
    render(<TreasurySection circleId={ID} />);

    expect(await screen.findByText("£30.05")).toBeInTheDocument();
    expect(screen.getByText("£100.10")).toBeInTheDocument();
    expect(screen.getByText(/from 4 completed ledger transactions/)).toBeInTheDocument();
    expect(screen.getByText(/2 pending and 1 failed/)).toBeInTheDocument();
  });

  it("activity: describes supported events", async () => {
    api.activity.mockResolvedValue(ACTIVITY);
    render(<ActivitySection circleId={ID} />);

    expect(await screen.findByText("Payout window 1 paid to Ada Obi")).toBeInTheDocument();
    expect(screen.getByText("Ada Obi created the circle")).toBeInTheDocument();
  });

  it("a failing section shows its own error with retry", async () => {
    api.treasury.mockRejectedValueOnce(new ApiError(500)).mockResolvedValueOnce(TREASURY);
    render(<TreasurySection circleId={ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("We couldn't load treasury");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("£30.05")).toBeInTheDocument();
  });
});

describe("circle detail failure isolation", () => {
  beforeEach(() => {
    navigation.params = { circleId: ID };
  });

  it("a failing section does not blank the page or other sections", async () => {
    api.get.mockResolvedValue(CIRCLE as unknown as Circle);
    api.treasury.mockRejectedValue(new ApiError(500));
    api.members.mockResolvedValue(MEMBERS);
    render(<CircleDetailPage />);

    await screen.findByRole("heading", { name: "Manchester Developers" });
    fireEvent.click(screen.getByRole("tab", { name: "Treasury" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("We couldn't load treasury");
    expect(screen.getByRole("heading", { name: "Manchester Developers" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Members" }));
    expect(await screen.findByText("Ada Obi")).toBeInTheDocument();
  });
});

describe("dashboard", () => {
  it("shows real counts and the next contribution", async () => {
    api.list.mockResolvedValue([MY_CIRCLE, OTHER_CIRCLE]);
    users.obligations.mockResolvedValue(MY_OBLIGATIONS);
    api.activity.mockResolvedValue(ACTIVITY);
    render(<DashboardPage />);

    const summary = await screen.findByRole("region", { name: "Summary" });
    const tile = (label: string) => within(summary).getByText(label).parentElement!;
    expect(tile("Circles")).toHaveTextContent("2");
    expect(tile("Active circles")).toHaveTextContent("1");
    expect(tile("Contributions due")).toHaveTextContent("1");
    expect(tile("Contributions due")).toHaveTextContent("Includes overdue contributions");
    expect(tile("Next contribution")).toHaveTextContent("£50.10");
    expect(tile("Next contribution")).toHaveTextContent("Manchester Developers");
    // One request for obligations, not one per circle.
    expect(users.obligations).toHaveBeenCalledTimes(1);
    expect(api.obligations).not.toHaveBeenCalled();
    expect(await screen.findAllByText("Ada Obi created the circle")).not.toHaveLength(0);
  });

  it("with no circles shows honest empty values", async () => {
    api.list.mockResolvedValue([]);
    users.obligations.mockResolvedValue([]);
    render(<DashboardPage />);

    const summary = await screen.findByRole("region", { name: "Summary" });
    expect(within(summary).getByText("None due")).toBeInTheDocument();
    expect(await screen.findByText("No activity to show yet")).toBeInTheDocument();
  });

  it("an obligations failure does not hide activity", async () => {
    api.list.mockResolvedValue([MY_CIRCLE]);
    users.obligations.mockRejectedValue(new ApiError(500));
    api.activity.mockResolvedValue(ACTIVITY);
    render(<DashboardPage />);

    expect(await screen.findByText("We couldn't load your summary")).toBeInTheDocument();
    expect(await screen.findByText("Ada Obi created the circle")).toBeInTheDocument();
  });

  it("one circle's activity failing is reported, the rest still shown", async () => {
    api.list.mockResolvedValue([MY_CIRCLE, OTHER_CIRCLE]);
    users.obligations.mockResolvedValue([]);
    api.activity.mockResolvedValueOnce(ACTIVITY).mockRejectedValueOnce(new ApiError(500));
    render(<DashboardPage />);

    expect(await screen.findByText(/Activity couldn.t be loaded for: Leeds Savers/)).toBeInTheDocument();
    expect(screen.getByText("Ada Obi created the circle")).toBeInTheDocument();
  });

  it("circle list failure shows an error, not zeros", async () => {
    api.list.mockRejectedValue(new ApiError(500));
    users.obligations.mockResolvedValue([]);
    render(<DashboardPage />);

    const alerts = await screen.findAllByRole("alert");
    expect(alerts[0]).toHaveTextContent("We couldn't load your summary");
    expect(screen.queryByRole("region", { name: "Summary" })).not.toBeInTheDocument();
  });
});

describe("payments and payouts pages", () => {
  it("payments lists own obligations across circles without a pay action", async () => {
    users.obligations.mockResolvedValue(MY_OBLIGATIONS);
    render(<MyPayments />);

    const table = await screen.findByRole("table");
    expect(within(table).getAllByText("Manchester Developers")).toHaveLength(2);
    expect(within(table).getByText("£50.10")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("payments error state", async () => {
    users.obligations.mockRejectedValue(new ApiError(503));
    render(<MyPayments />);
    expect(await screen.findByText("We couldn't load your contributions")).toBeInTheDocument();
  });

  it("payments empty state", async () => {
    users.obligations.mockResolvedValue([]);
    render(<MyPayments />);
    expect(await screen.findByText("No contributions to show yet")).toBeInTheDocument();
  });

  it("payouts lists decided payouts and open windows", async () => {
    api.list.mockResolvedValue([MY_CIRCLE]);
    api.payouts.mockResolvedValue(PAYOUTS);
    render(<MyPayouts />);

    expect(await screen.findByText("Approved, not yet paid")).toBeInTheDocument();
    expect(screen.getByText(/payout window 3 is open/)).toBeInTheDocument();
  });

  it("payouts reports a failing circle", async () => {
    api.list.mockResolvedValue([MY_CIRCLE]);
    api.payouts.mockRejectedValue(new ApiError(503));
    render(<MyPayouts />);
    expect(await screen.findByText("Some payouts couldn't be loaded.")).toBeInTheDocument();
    expect(screen.getByText("No payouts yet")).toBeInTheDocument();
  });
});
