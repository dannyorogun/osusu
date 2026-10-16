import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PayoutWindowPanel } from "@/components/circles/PayoutWindowPanel";
import { osusu } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/errors";
import type { PayoutWindow } from "@/types/payment";

vi.mock("@/lib/api/endpoints", () => ({
  osusu: {
    payoutWindows: {
      current: vi.fn(), open: vi.fn(), vote: vi.fn(), approve: vi.fn(), execute: vi.fn(),
    },
  },
}));

const api = vi.mocked(osusu.payoutWindows);
const CIRCLE_ID = "c1";

const OPEN: PayoutWindow = {
  payout_window: 1,
  state: "open",
  candidates: [
    { id: "p-ada", display_name: "Ada Obi", is_you: true, status: "pending" },
    { id: "p-bola", display_name: "Bola", is_you: false, status: "pending" },
  ],
  votes_cast: 1,
  votes_required: 2,
  your_vote: null,
  payout: null,
  can_vote: true,
  can_approve: false,
  can_execute: false,
};

const APPROVED: PayoutWindow = {
  ...OPEN,
  state: "approved",
  candidates: [
    { id: "p-ada", display_name: "Ada Obi", is_you: true, status: "cancelled" },
    { id: "p-bola", display_name: "Bola", is_you: false, status: "approved" },
  ],
  votes_cast: null,
  votes_required: null,
  can_vote: false,
  payout: {
    id: "p-bola", payout_window: 1, amount: "200.00", status: "approved", recipient: "Bola",
    is_you: false, created_at: "2026-10-01T00:00:00Z", approved_at: "2026-10-02T00:00:00Z", paid_at: null,
    attempt_state: null,
  },
  can_execute: true,
};

const PAID: PayoutWindow = {
  ...APPROVED,
  state: "paid",
  can_execute: false,
  payout: { ...APPROVED.payout!, status: "paid", paid_at: "2026-10-03T00:00:00Z" },
};

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
});

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("payout window panel", () => {
  it("no window: the creator can open one, others cannot", async () => {
    api.current.mockResolvedValue({ window: null, can_open_window: true });
    api.open.mockResolvedValue({ window: OPEN });
    const onChanged = vi.fn();
    render(<PayoutWindowPanel circleId={CIRCLE_ID} onChanged={onChanged} />);

    fireEvent.click(await screen.findByRole("button", { name: "Open the next payout window" }));

    expect(await screen.findByText("Payout window opened. Members can now vote.")).toBeInTheDocument();
    expect(api.open).toHaveBeenCalledWith(CIRCLE_ID);
    // The re-read is fired from the reload after the feedback renders.
    await waitFor(() => expect(api.current).toHaveBeenCalledTimes(2));
    expect(onChanged).toHaveBeenCalled();
  });

  it("members without permission see no open button", async () => {
    api.current.mockResolvedValue({ window: null, can_open_window: false });
    render(<PayoutWindowPanel circleId={CIRCLE_ID} onChanged={vi.fn()} />);
    expect(await screen.findByText("No payout window has been opened yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows candidates and quorum progress, never who voted", async () => {
    api.current.mockResolvedValue({ window: OPEN, can_open_window: false });
    render(<PayoutWindowPanel circleId={CIRCLE_ID} onChanged={vi.fn()} />);

    expect(await screen.findByText("Voting open")).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 required votes cast/)).toHaveTextContent("Who voted for whom is not shown.");
    const list = screen.getByRole("list", { name: "Candidates" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Approve the window" })).not.toBeInTheDocument();
  });

  it("casts a vote, prevents duplicates while pending, then re-reads the window", async () => {
    const vote = deferred<{ window: PayoutWindow }>();
    api.current
      .mockResolvedValueOnce({ window: OPEN, can_open_window: false })
      .mockResolvedValue({ window: { ...OPEN, votes_cast: 2, can_vote: false, your_vote: "p-bola" }, can_open_window: false });
    api.vote.mockReturnValue(vote.promise);
    render(<PayoutWindowPanel circleId={CIRCLE_ID} onChanged={vi.fn()} />);

    const button = await screen.findByRole("button", { name: "Vote for Bola" });
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("button", { name: "Vote for Ada Obi" }));
    expect(api.vote).toHaveBeenCalledTimes(1);
    expect(api.vote).toHaveBeenCalledWith(CIRCLE_ID, 1, "p-bola");
    expect(screen.getByRole("button", { name: "Vote for Ada Obi" })).toBeDisabled();

    vote.resolve({ window: OPEN });
    expect(await screen.findByText("Your vote for Bola was recorded.")).toBeInTheDocument();
    expect(await screen.findByText("Your vote")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Vote for/ })).not.toBeInTheDocument();
  });

  it("shows a backend vote refusal", async () => {
    api.current.mockResolvedValue({ window: OPEN, can_open_window: false });
    api.vote.mockRejectedValue(new ApiError(400, { error: "Only eligible members can vote." }));
    render(<PayoutWindowPanel circleId={CIRCLE_ID} onChanged={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Vote for Bola" }));
    expect(await screen.findByText("Only eligible members can vote.")).toBeInTheDocument();
  });

  it("says when the user cannot vote", async () => {
    api.current.mockResolvedValue({ window: { ...OPEN, can_vote: false }, can_open_window: false });
    render(<PayoutWindowPanel circleId={CIRCLE_ID} onChanged={vi.fn()} />);
    expect(await screen.findByText("You are not eligible to vote in this window.")).toBeInTheDocument();
  });

  it("shows the quorum refusal on approval and keeps the window open", async () => {
    api.current.mockResolvedValue({ window: { ...OPEN, can_approve: true }, can_open_window: false });
    api.approve.mockRejectedValue(
      new ApiError(400, { error: "Quorum not reached: 1 of 2 required votes.", window: OPEN }),
    );
    render(<PayoutWindowPanel circleId={CIRCLE_ID} onChanged={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Approve the window" }));
    expect(await screen.findByText("Quorum not reached: 1 of 2 required votes.")).toBeInTheDocument();
    expect(screen.getByText("Voting open")).toBeInTheDocument();
  });

  it("approval says nothing has been paid", async () => {
    api.current
      .mockResolvedValueOnce({ window: { ...OPEN, can_approve: true }, can_open_window: false })
      .mockResolvedValue({ window: APPROVED, can_open_window: false });
    api.approve.mockResolvedValue({ window: APPROVED });
    render(<PayoutWindowPanel circleId={CIRCLE_ID} onChanged={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Approve the window" }));
    expect(await screen.findByText(/nothing has been paid yet/)).toBeInTheDocument();
    expect(await screen.findAllByText("Approved, not yet paid")).toHaveLength(2); // window + recipient
    expect(screen.getByText("£200.00 to Bola.")).toBeInTheDocument();
  });

  it("does not show paid until the backend confirms", async () => {
    const execute = deferred<{ window: PayoutWindow; result: "paid" }>();
    api.current
      .mockResolvedValueOnce({ window: APPROVED, can_open_window: false })
      .mockResolvedValue({ window: PAID, can_open_window: true });
    api.execute.mockReturnValue(execute.promise);
    const onChanged = vi.fn();
    render(<PayoutWindowPanel circleId={CIRCLE_ID} onChanged={onChanged} />);

    fireEvent.click(await screen.findByRole("button", { name: "Pay out" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Confirm payout" }));
    expect(api.execute).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/^Paid$/)).not.toBeInTheDocument();
    expect(screen.queryByText("Payout confirmed by Osusu.")).not.toBeInTheDocument();

    execute.resolve({ window: PAID, result: "paid" });
    expect(await screen.findByText("Payout confirmed by Osusu.")).toBeInTheDocument();
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(await screen.findByText("£200.00 to Bola, paid 3 Oct 2026.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open the next payout window" })).toBeInTheDocument();
  });

  it("a repeated execution reports already paid", async () => {
    api.current.mockResolvedValue({ window: APPROVED, can_open_window: false });
    api.execute.mockResolvedValue({ window: PAID, result: "already_paid" });
    render(<PayoutWindowPanel circleId={CIRCLE_ID} onChanged={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Pay out" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Confirm payout" }));
    expect(await screen.findByText("This payout was already paid. Nothing was paid again.")).toBeInTheDocument();
  });

  it("a confirmed provider failure is shown as not paid and offers a retry", async () => {
    const FAILED: PayoutWindow = {
      ...APPROVED, state: "failed", payout: { ...APPROVED.payout!, status: "failed", attempt_state: "failed" },
    };
    api.current
      .mockResolvedValueOnce({ window: APPROVED, can_open_window: false })
      .mockResolvedValue({ window: FAILED, can_open_window: false });
    api.execute.mockRejectedValue(new ApiError(502, { result: "failed" }));
    render(<PayoutWindowPanel circleId={CIRCLE_ID} onChanged={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Pay out" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Confirm payout" }));

    expect(
      await screen.findByText("The payout provider confirmed the payment failed. Nothing was paid; it can be executed again."),
    ).toBeInTheDocument();
    expect(await screen.findAllByText("Payment failed, not paid")).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: "Retry the payout" })).toBeInTheDocument();
    expect(screen.queryByText(/paid \d/)).not.toBeInTheDocument();
  });

  it("an unknown outcome is never shown as failed and offers no retry", async () => {
    const PROCESSING: PayoutWindow = {
      ...APPROVED, state: "processing", can_execute: false,
      payout: { ...APPROVED.payout!, status: "processing", attempt_state: "unknown" },
    };
    api.current
      .mockResolvedValueOnce({ window: APPROVED, can_open_window: false })
      .mockResolvedValue({ window: PROCESSING, can_open_window: false });
    api.execute.mockResolvedValue({ window: PROCESSING, result: "unknown" });
    render(<PayoutWindowPanel circleId={CIRCLE_ID} onChanged={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Pay out" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Confirm payout" }));

    expect(await screen.findByText(/could not be confirmed. It has not been marked failed/)).toBeInTheDocument();
    expect(await screen.findByText(/It has not failed and must not be paid again/)).toBeInTheDocument();
    expect(screen.getAllByText("Payment being confirmed")).not.toHaveLength(0);
    expect(screen.queryByText("Payment failed, not paid")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Retry the payout|Pay out/ })).not.toBeInTheDocument();
  });

  it("a repeated execute while an attempt is unresolved (409) sends nothing", async () => {
    api.current.mockResolvedValue({ window: APPROVED, can_open_window: false });
    api.execute.mockRejectedValue(new ApiError(409, { result: "in_progress" }));
    render(<PayoutWindowPanel circleId={CIRCLE_ID} onChanged={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Pay out" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Confirm payout" }));

    expect(await screen.findByText(/still being confirmed. It will not be sent again/)).toBeInTheDocument();
  });

  it("disabled payouts (503) say nothing was paid and keep the payout approved", async () => {
    api.current.mockResolvedValue({ window: APPROVED, can_open_window: false });
    api.execute.mockRejectedValue(new ApiError(503, { result: "unavailable" }));
    render(<PayoutWindowPanel circleId={CIRCLE_ID} onChanged={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Pay out" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Confirm payout" }));

    expect(await screen.findByText("Payouts are not enabled on this server yet. Nothing was paid.")).toBeInTheDocument();
    expect(screen.queryByText(/paid \d/)).not.toBeInTheDocument();
  });

  it("load errors are retryable", async () => {
    api.current.mockRejectedValueOnce(new ApiError(500)).mockResolvedValue({ window: OPEN, can_open_window: false });
    render(<PayoutWindowPanel circleId={CIRCLE_ID} onChanged={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Voting open")).toBeInTheDocument();
  });
});
