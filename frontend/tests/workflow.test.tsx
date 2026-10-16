import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AcceptInvitation } from "@/components/circles/AcceptInvitation";
import { PayoutsSection, TrustSection } from "@/components/circles/CircleDataSections";
import { CircleWorkflow } from "@/components/circles/CircleWorkflow";
import { useApiResource } from "@/hooks/useApiResource";
import { osusu } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/errors";
import type { Circle, CircleMember, TrustSummary } from "@/types/circle";

import { CIRCLE } from "./helpers";

vi.mock("@/lib/api/endpoints", () => ({
  osusu: {
    circles: {
      members: vi.fn(), invite: vi.fn(), acceptConstitution: vi.fn(), evaluate: vi.fn(),
      lock: vi.fn(), trust: vi.fn(), payouts: vi.fn(), acceptInvitation: vi.fn(),
    },
    payoutWindows: { current: vi.fn().mockResolvedValue({ window: null, can_open_window: false }) },
  },
}));

const api = vi.mocked(osusu.circles);
const circle = (status: Circle["status"], extra: Partial<Circle> = {}) =>
  ({ ...CIRCLE, status, ...extra }) as unknown as Circle;

const member = (overrides: Partial<CircleMember>): CircleMember => ({
  id: "m", display_name: "Ada Obi", username: "ada", status: "active",
  joined_at: "2026-09-02T09:30:00Z", constitution_accepted: false,
  constitution_accepted_at: null, is_creator: false, is_you: false, ...overrides,
});
const CREATOR_ME = member({ id: "m1", is_creator: true, is_you: true });
const OTHER = member({ id: "m2", display_name: "Bola", username: "bola", constitution_accepted: true });

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

describe("circle set-up workflow", () => {
  it("shows the backend status and constitution acceptance count", async () => {
    api.members.mockResolvedValue([CREATOR_ME, OTHER]);
    render(<CircleWorkflow circle={circle("recruiting")} onChanged={vi.fn()} />);

    expect(await screen.findByText("1 of 2 active members have accepted the constitution.")).toBeInTheDocument();
    expect(screen.getByText("Recruiting")).toBeInTheDocument();
  });

  it("accepts the constitution, then reloads the circle and members", async () => {
    const onChanged = vi.fn();
    api.members.mockResolvedValue([CREATOR_ME, OTHER]);
    api.acceptConstitution.mockResolvedValue({
      accepted: true, circle_id: CIRCLE.id, membership_id: "m1", accepted_at: "2026-10-09T00:00:00Z",
    });
    render(<CircleWorkflow circle={circle("recruiting")} onChanged={onChanged} />);

    fireEvent.click(await screen.findByRole("button", { name: "Accept the constitution" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(api.acceptConstitution).toHaveBeenCalledWith(CIRCLE.id);
    expect(api.members).toHaveBeenCalledTimes(2);
  });

  it("shows a backend refusal for constitution acceptance", async () => {
    api.members.mockResolvedValue([CREATOR_ME]);
    api.acceptConstitution.mockRejectedValue(
      new ApiError(400, { accepted: false, error: "The circle constitution can no longer be accepted." }),
    );
    render(<CircleWorkflow circle={circle("recruiting")} onChanged={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Accept the constitution" }));

    expect(await screen.findByText("The circle constitution can no longer be accepted.")).toBeInTheDocument();
  });

  it("creates an invitation and shows the code to share", async () => {
    api.members.mockResolvedValue([CREATOR_ME]);
    api.invite.mockResolvedValue({
      invited: true, invitation_id: "i1", email: "bola@example.com",
      expires_at: "2026-10-16T00:00:00Z", token: "tok-123",
    });
    render(<CircleWorkflow circle={circle("recruiting")} onChanged={vi.fn()} />);

    fireEvent.change(await screen.findByLabelText("Email address"), { target: { value: "bola@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));

    expect(await screen.findByText("Invitation created for bola@example.com.")).toBeInTheDocument();
    expect(screen.getByText("tok-123")).toBeInTheDocument();
    expect(api.invite).toHaveBeenCalledWith(CIRCLE.id, "bola@example.com");
  });

  it("shows invitation errors from the backend and needs an email first", async () => {
    api.members.mockResolvedValue([CREATOR_ME]);
    api.invite.mockRejectedValue(
      new ApiError(400, { invited: false, error: "A pending invitation already exists for this email." }),
    );
    render(<CircleWorkflow circle={circle("recruiting")} onChanged={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Create invitation" }));
    expect(screen.getByText("Enter the email address of the person you're inviting.")).toBeInTheDocument();
    expect(api.invite).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "x@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));
    expect(await screen.findByText("A pending invitation already exists for this email.")).toBeInTheDocument();
  });

  it("closes invitations outside recruiting", async () => {
    api.members.mockResolvedValue([CREATOR_ME]);
    render(<CircleWorkflow circle={circle("ready")} onChanged={vi.fn()} />);
    expect(await screen.findByText("Invitations are closed while the circle is ready.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create invitation" })).not.toBeInTheDocument();
  });

  it("does not submit twice while a request is in flight", async () => {
    api.members.mockResolvedValue([CREATOR_ME]);
    const pending = deferred<never>();
    api.evaluate.mockReturnValue(pending.promise);
    render(<CircleWorkflow circle={circle("recruiting")} onChanged={vi.fn()} />);

    const button = await screen.findByRole("button", { name: "Run formation checks" });
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);

    expect(api.evaluate).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /Checking/ })).toBeDisabled();
  });

  it("shows failed formation checks without changing anything", async () => {
    const onChanged = vi.fn();
    api.members.mockResolvedValue([CREATOR_ME]);
    api.evaluate.mockResolvedValue({
      ready: false,
      formation_checks: { minimum_members: false, constitution_accepted: true },
      financial_checks: null,
    });
    render(<CircleWorkflow circle={circle("recruiting")} onChanged={onChanged} />);

    fireEvent.click(await screen.findByRole("button", { name: "Run formation checks" }));

    expect(await screen.findByText("Not ready yet.")).toBeInTheDocument();
    const failed = screen.getByText("At least 2 active members").closest("li")!;
    expect(failed).toHaveTextContent("Failed:");
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("a passing evaluation reloads the circle", async () => {
    const onChanged = vi.fn();
    api.members.mockResolvedValue([CREATOR_ME]);
    api.evaluate.mockResolvedValue({
      ready: true,
      formation_checks: { minimum_members: true },
      financial_checks: { passed: true, checks: { payout_matches_cycle: true } },
      cash_flow: { passed: true, failures: [] },
    });
    render(<CircleWorkflow circle={circle("recruiting")} onChanged={onChanged} />);

    fireEvent.click(await screen.findByRole("button", { name: "Run formation checks" }));

    expect(await screen.findByText("All checks passed. The circle is Ready.")).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("offers the lock only when the backend says the circle is ready", async () => {
    api.members.mockResolvedValue([CREATOR_ME]);
    render(<CircleWorkflow circle={circle("recruiting")} onChanged={vi.fn()} />);

    expect(await screen.findByText("Available once the formation checks pass and the circle is Ready.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Financially lock the circle" })).not.toBeInTheDocument();
  });

  it("shows the requirements the backend says failed when locking", async () => {
    const onChanged = vi.fn();
    api.members.mockResolvedValue([CREATOR_ME]);
    api.lock.mockRejectedValue(new ApiError(400, {
      locked: false,
      error: "Circle cannot be financially locked.",
      checks: { cash_flow_valid: false, circle_ready: true, formation_valid: true, financial_integrity: true },
    }));
    render(<CircleWorkflow circle={circle("ready")} onChanged={onChanged} />);

    fireEvent.click(await screen.findByRole("button", { name: "Financially lock the circle" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Lock circle" }));

    expect(await screen.findByText("Circle cannot be financially locked.")).toBeInTheDocument();
    expect(screen.getByText("Treasury never runs short during the cycle").closest("li")).toHaveTextContent("Failed:");
    expect(onChanged).not.toHaveBeenCalled();
    expect(screen.queryByText("The circle is financially locked.")).not.toBeInTheDocument();
  });

  it("a successful lock reloads the circle", async () => {
    const onChanged = vi.fn();
    api.members.mockResolvedValue([CREATOR_ME]);
    api.lock.mockResolvedValue({ locked: true, circle: circle("locked") });
    render(<CircleWorkflow circle={circle("ready")} onChanged={onChanged} />);

    fireEvent.click(await screen.findByRole("button", { name: "Financially lock the circle" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Lock circle" }));

    expect(await screen.findByText("The circle is financially locked.")).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("members who are not the creator get no creator actions", async () => {
    api.members.mockResolvedValue([member({ is_you: true }), member({ id: "c", is_creator: true })]);
    render(<CircleWorkflow circle={circle("ready")} onChanged={vi.fn()} />);

    expect(await screen.findByText(/Only the circle creator can run the formation checks/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run formation checks" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Financially lock the circle" })).not.toBeInTheDocument();
  });

  it("a locked circle shows the lock date and no actions", async () => {
    api.members.mockResolvedValue([member({ is_you: true, is_creator: true, constitution_accepted: true })]);
    render(
      <CircleWorkflow
        circle={circle("locked", { financial_locked_at: "2026-10-09T10:00:00Z" })}
        onChanged={vi.fn()}
      />,
    );

    expect(await screen.findByText("The circle was financially locked on 9 Oct 2026.")).toBeInTheDocument();
    expect(screen.getByText("Formation has already been completed.")).toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });
});

describe("accept invitation", () => {
  it.each([
    ["Invitation has expired."],
    ["Invitation is no longer valid."],
    ["This invitation was not sent to your email address."],
  ])("shows the backend reason: %s", async (message) => {
    api.acceptInvitation.mockRejectedValue(new ApiError(400, { accepted: false, error: message }));
    render(<AcceptInvitation />);

    fireEvent.click(screen.getByRole("button", { name: "Accept an invitation" }));
    fireEvent.change(screen.getByLabelText("Invitation code"), { target: { value: "tok" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Join circle" }));
    });

    expect(await screen.findByText(message)).toBeInTheDocument();
  });

  it("an unknown code is reported without detail", async () => {
    api.acceptInvitation.mockRejectedValue(new ApiError(404, { detail: "Not found." }));
    render(<AcceptInvitation />);

    fireEvent.click(screen.getByRole("button", { name: "Accept an invitation" }));
    fireEvent.change(screen.getByLabelText("Invitation code"), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Join circle" }));

    expect(await screen.findByText("We couldn't find what you were looking for.")).toBeInTheDocument();
  });
});

const TRUST: TrustSummary = {
  data_status: "available",
  your_record_in_circle: { total: 2, pending: 0, paid: 1, overdue: 1, waived: 0 },
  your_history: { completed_circles: 0, paid_contributions: 3, overdue_contributions: 1 },
  circle: { active_members: 3, invitation_connections: 2 },
  score: null,
  score_unavailable_reasons: ["No validated trust score exists.", "Circle health treats missing data as perfect."],
};

describe("trust section", () => {
  it("shows factual counts and why there is no score", async () => {
    api.trust.mockResolvedValue(TRUST);
    const { container } = render(<TrustSection circleId={CIRCLE.id} />);

    expect(await screen.findByText("No trust score is shown.")).toBeInTheDocument();
    expect(screen.getByText("No validated trust score exists.")).toBeInTheDocument();
    expect(screen.getByText("Paid across your circles").nextSibling).toHaveTextContent("3");
    expect(screen.getByText(/2 invitation connections between members/)).toBeInTheDocument();
    expect(container).not.toHaveTextContent(/score:|\d+%|\/100/);
  });

  it("insufficient data is not presented as low trust", async () => {
    api.trust.mockResolvedValue({
      ...TRUST,
      data_status: "insufficient_data",
      your_record_in_circle: { total: 1, pending: 1, paid: 0, overdue: 0, waived: 0 },
      your_history: { completed_circles: 0, paid_contributions: 0, overdue_contributions: 0 },
    });
    render(<TrustSection circleId={CIRCLE.id} />);

    expect(await screen.findByText(/Not enough history yet/)).toHaveTextContent("This is not a sign of low trust.");
  });

  it("shows an error with retry", async () => {
    api.trust.mockRejectedValueOnce(new ApiError(500)).mockResolvedValueOnce(TRUST);
    render(<TrustSection circleId={CIRCLE.id} />);

    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No trust score is shown.")).toBeInTheDocument();
  });
});

describe("payout status display", () => {
  it("a failed payout is shown as not paid", async () => {
    api.payouts.mockResolvedValue({
      payouts: [{
        id: "p1", payout_window: 1, amount: "200.00", status: "failed", recipient: "Bola",
        is_you: false, created_at: "2026-10-01T00:00:00Z", approved_at: "2026-10-02T00:00:00Z", paid_at: null,
        attempt_state: "failed",
      }],
      open_windows: [],
    });
    render(<PayoutsSection circleId={CIRCLE.id} />);

    expect(await screen.findByText("Payment failed, not paid")).toBeInTheDocument();
    expect(screen.queryByText("Paid")).not.toBeInTheDocument();
  });
});

describe("useApiResource keepPreviousData", () => {
  function Probe({ load, keep }: { load: () => Promise<string>; keep: boolean }) {
    const r = useApiResource(load, "probe", { keepPreviousData: keep });
    return (
      <div>
        <span>{r.status}:{r.data ?? "-"}:{r.refreshing ? "refreshing" : "idle"}</span>
        <button onClick={r.reload}>reload</button>
      </div>
    );
  }

  it("keeps the last data while reloading", async () => {
    const second = deferred<string>();
    const load = vi.fn().mockResolvedValueOnce("v1").mockReturnValueOnce(second.promise);
    render(<Probe load={load} keep />);

    expect(await screen.findByText("success:v1:idle")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "reload" }));
    expect(await screen.findByText("success:v1:refreshing")).toBeInTheDocument();
    await act(async () => second.resolve("v2"));
    expect(await screen.findByText("success:v2:idle")).toBeInTheDocument();
  });

  it("without the option a reload shows loading", async () => {
    const load = vi.fn().mockResolvedValueOnce("v1").mockReturnValueOnce(new Promise(() => {}));
    render(<Probe load={load} keep={false} />);

    expect(await screen.findByText("success:v1:idle")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "reload" }));
    expect(await screen.findByText("loading:-:idle")).toBeInTheDocument();
  });
});
