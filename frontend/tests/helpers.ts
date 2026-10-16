import { vi } from "vitest";

/** A JSON Response as fetch would return it. */
export function jsonResponse(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** fetch mock answering each call from the queue, in order. */
export function queuedFetch(...responses: Array<Response | Error>) {
  const queue = [...responses];
  return vi.fn(async () => {
    const next = queue.shift();
    if (!next) throw new Error("Unexpected fetch call");
    if (next instanceof Error) throw next;
    return next;
  });
}

export const USER = {
  id: "7a0c2f0e-2f6c-4a8f-9a55-0f5f3c9b1e21",
  email: "ada@example.com",
  username: "ada",
  first_name: "Ada",
  last_name: "Obi",
  is_verified: false,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T10:00:00Z",
};

export const CIRCLE = {
  id: "0b0f8a52-6c1b-4b39-8d0c-2d8f4a8f7e11",
  name: "Manchester Developers",
  description: "Saving together for conference tickets.",
  status: "recruiting",
  created_at: "2026-09-02T09:30:00Z",
  updated_at: "2026-09-02T09:30:00Z",
  financial_locked_at: null,
  constitution: {
    member_limit: 5,
    contribution_amount: "50.00",
    contribution_frequency: "weekly",
    payout_amount: "100.00",
    payout_frequency: "biweekly",
    cycle_length: 2,
    quorum_percentage: 60,
    grace_period_days: 7,
    reserve_enabled: true,
    reserve_amount: "25.00",
    allow_replacement_before_lock: false,
  },
} as const;
