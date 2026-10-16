import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CircleDetailPage from "@/app/(app)/circles/[circleId]/page";
import { AssistantPanel } from "@/components/circles/AssistantPanel";
import { CircleList } from "@/components/circles/CircleList";
import {
  CreateCircleForm,
  INITIAL_VALUES,
  toRequest,
  validateCreateCircle,
} from "@/components/circles/CreateCircleForm";
import { osusu } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/errors";
import type { Circle, MyCircle } from "@/types/circle";

import { CIRCLE } from "./helpers";
import { navigation, router } from "./router";

vi.mock("@/lib/api/endpoints", () => ({
  osusu: {
    circles: {
      get: vi.fn(), create: vi.fn(), acceptInvitation: vi.fn(),
      members: vi.fn(), obligations: vi.fn(), payouts: vi.fn(), treasury: vi.fn(), activity: vi.fn(),
      trust: vi.fn(),
    },
    assistant: { ask: vi.fn() },
  },
}));

const circles = vi.mocked(osusu.circles);
const assistant = vi.mocked(osusu.assistant);
const circle = CIRCLE as unknown as Circle;
const myCircle = { ...CIRCLE, member_count: 3 } as unknown as MyCircle;

beforeEach(() => {
  circles.get.mockReset();
  circles.create.mockReset();
  assistant.ask.mockReset();
});

describe("CircleList", () => {
  it("renders backend values as given", () => {
    render(<CircleList circles={[myCircle]} />);
    const link = screen.getByRole("link", { name: /Manchester Developers/ });
    expect(link).toHaveAttribute("href", `/circles/${CIRCLE.id}`);
    expect(link).toHaveTextContent("£50.00 weekly");
    expect(link).toHaveTextContent("3 of 5 members");
    expect(link).toHaveTextContent("Recruiting");
  });

  it("shows a helpful empty state", () => {
    render(<CircleList circles={[]} />);
    expect(screen.getByText("You haven't joined a circle yet.")).toBeInTheDocument();
    expect(screen.getByText(/accept an invitation from someone you trust/)).toBeInTheDocument();
  });
});

describe("circle detail page", () => {
  beforeEach(() => {
    navigation.params = { circleId: CIRCLE.id };
  });

  it("loads then shows the circle and its constitution", async () => {
    circles.get.mockResolvedValue(circle);
    render(<CircleDetailPage />);

    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
    expect(await screen.findByRole("heading", { name: "Manchester Developers" })).toBeInTheDocument();
    expect(circles.get).toHaveBeenCalledWith(CIRCLE.id);

    fireEvent.click(screen.getByRole("tab", { name: "Constitution" }));
    expect(screen.getByText("£50.00 weekly")).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument();
  });

  it("treats 404/403 as not available without revealing why", async () => {
    circles.get.mockRejectedValue(new ApiError(404, { detail: "Circle not found." }));
    render(<CircleDetailPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Circle not available");
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("offers retry on other API errors", async () => {
    circles.get.mockRejectedValueOnce(new ApiError(500)).mockResolvedValueOnce(circle);
    render(<CircleDetailPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong on our side");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Manchester Developers" })).toBeInTheDocument();
  });
});

describe("create circle", () => {
  const valid = {
    ...INITIAL_VALUES,
    name: "Savers",
    member_limit: "5",
    contribution_amount: "50",
    payout_amount: "100.00",
    cycle_length: "2",
    quorum_percentage: "60",
    grace_period_days: "7",
  };

  it("mirrors the backend serializer limits", () => {
    expect(validateCreateCircle(valid)).toEqual({});
    const errors = validateCreateCircle({
      ...valid,
      name: " ",
      member_limit: "1",
      contribution_amount: "0.00",
      payout_amount: "12.345",
      cycle_length: "0",
      quorum_percentage: "101",
      grace_period_days: "-1",
      reserve_amount: "abc",
    });
    expect(Object.keys(errors).sort()).toEqual([
      "contribution_amount", "cycle_length", "grace_period_days", "member_limit",
      "name", "payout_amount", "quorum_percentage", "reserve_amount",
    ]);
  });

  it("sends amounts as decimal strings, unchanged", () => {
    const request = toRequest(valid);
    expect(request.contribution_amount).toBe("50");
    expect(request.payout_amount).toBe("100.00");
    expect(request.member_limit).toBe(5);
  });

  it("blocks invalid input without calling the API", async () => {
    render(<CreateCircleForm />);
    fireEvent.click(screen.getByRole("button", { name: "Create circle" }));

    expect(await screen.findByText("Give your circle a name.")).toBeInTheDocument();
    expect(circles.create).not.toHaveBeenCalled();
  });

  function fillValid() {
    const fields: Record<string, string> = {
      "Circle name": "Savers",
      "Member limit": "5",
      "Contribution amount (£)": "50.00",
      "Payout amount (£)": "100.00",
      "Cycle length": "2",
      "Quorum (%)": "60",
      "Grace period (days)": "7",
    };
    for (const [label, value] of Object.entries(fields)) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    }
  }

  it("creates the circle and redirects to it", async () => {
    circles.create.mockResolvedValue(circle);
    render(<CreateCircleForm />);
    fillValid();
    fireEvent.click(screen.getByRole("button", { name: "Create circle" }));

    await waitFor(() => expect(router.push).toHaveBeenCalledWith(`/circles/${CIRCLE.id}?created=1`));
    expect(circles.create).toHaveBeenCalledWith(expect.objectContaining({
      name: "Savers", contribution_amount: "50.00", contribution_frequency: "weekly",
    }));
  });

  it("shows backend validation errors on their fields", async () => {
    circles.create.mockRejectedValue(new ApiError(400, {
      member_limit: ["Ensure this value is less than or equal to 100."],
    }));
    render(<CreateCircleForm />);
    fillValid();
    fireEvent.click(screen.getByRole("button", { name: "Create circle" }));

    expect(await screen.findByText("Ensure this value is less than or equal to 100.")).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });
});

describe("assistant panel", () => {
  it("shows the backend's 503 as unavailable and never fakes an answer", async () => {
    assistant.ask.mockRejectedValue(new ApiError(503, { code: "assistant_unavailable" }));
    render(<AssistantPanel circleId={CIRCLE.id} />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "What is our balance?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("AI assistance is currently unavailable.")).toBeInTheDocument();
    expect(screen.queryByText(/£/)).not.toBeInTheDocument();
  });
});
