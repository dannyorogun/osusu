"use client";

import { useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Spinner } from "@/components/ui/Spinner";
import { Alert, Badge, ErrorState } from "@/components/ui/Surface";
import { useApiResource } from "@/hooks/useApiResource";
import { osusu } from "@/lib/api/endpoints";
import { isApiError, userMessage } from "@/lib/api/errors";
import { formatDate, formatMoney } from "@/lib/utils/format";
import type { PayoutWindow } from "@/types/payment";

import { PAYOUT_STATUS } from "./labels";

/**
 * The circle's current payout window: candidates, voting, approval and
 * execution. Every state shown is the backend's; buttons appear only when
 * the backend says the action is available to this user, and Django
 * re-checks eligibility, quorum, funds and idempotency on every request.
 * A payout is shown as paid only when Django returns it as paid.
 */

const STATE: Record<PayoutWindow["state"], { label: string; tone: "info" | "warning" | "success" | "danger" | "neutral" }> = {
  open: { label: "Voting open", tone: "info" },
  approved: { label: "Approved, not yet paid", tone: "warning" },
  processing: { label: "Payment being confirmed", tone: "warning" },
  paid: { label: "Paid", tone: "success" },
  failed: { label: "Payment failed, not paid", tone: "danger" },
  returned: { label: "Payment returned, not paid", tone: "danger" },
  closed: { label: "Closed", tone: "neutral" },
};

const UNKNOWN_TEXT =
  "The payment outcome could not be confirmed. It has not been marked failed and will not be sent again until its status is resolved.";
const IN_PROGRESS_TEXT =
  "A payment attempt for this payout is still being confirmed. It will not be sent again until its status is resolved.";

type Feedback = { tone: "success" | "danger" | "warning"; text: string } | null;

export function PayoutWindowPanel({
  circleId,
  onChanged,
}: {
  circleId: string;
  onChanged: () => void;
}) {
  const current = useApiResource(
    () => osusu.payoutWindows.current(circleId),
    `payout-window:${circleId}`,
    { keepPreviousData: true },
  );
  const busy = useRef(false);
  const [pending, setPending] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [confirmExecute, setConfirmExecute] = useState(false);

  async function act(name: string, action: () => Promise<{ result?: string }>, success: string) {
    if (busy.current) return;
    busy.current = true;
    setPending(name);
    setFeedback(null);
    try {
      const response = await action();
      setFeedback(
        response.result === "already_paid"
          ? { tone: "success", text: "This payout was already paid. Nothing was paid again." }
          : response.result === "submitted"
            ? { tone: "warning", text: "The payout provider accepted the payment. It is not paid until settlement is confirmed." }
            : response.result === "unknown"
              ? { tone: "warning", text: UNKNOWN_TEXT }
              : { tone: "success", text: success },
      );
    } catch (caught) {
      const status = name === "execute" && isApiError(caught) ? caught.status : null;
      // 502 = the provider CONFIRMED the payment failed (no money moved, no
      // ledger entry). 409 = an earlier attempt is still being confirmed;
      // nothing was sent. 503 = payouts are disabled on this server.
      setFeedback(
        status === 409
          ? { tone: "warning", text: IN_PROGRESS_TEXT }
          : {
              tone: "danger",
              text:
                status === 502
                  ? "The payout provider confirmed the payment failed. Nothing was paid; it can be executed again."
                  : status === 503
                    ? "Payouts are not enabled on this server yet. Nothing was paid."
                    : userMessage(caught),
            },
      );
    } finally {
      busy.current = false;
      setPending(null);
      setConfirmExecute(false);
      // Always re-read: after any outcome the backend state is the truth.
      current.reload();
      onChanged();
    }
  }

  if (current.status === "loading") {
    return (
      <div className="flex items-center gap-2 py-4 text-sm text-muted">
        <Spinner label="Loading payout window" /> <span aria-hidden="true">Loading payout window…</span>
      </div>
    );
  }
  if (current.status === "error") {
    return (
      <ErrorState
        title="We couldn't load the payout window"
        message={userMessage(current.error)}
        onRetry={current.reload}
      />
    );
  }

  const { window, can_open_window: canOpen } = current.data;

  const openButton = canOpen && (
    <Button
      variant="secondary"
      loading={pending === "open"}
      loadingText="Opening"
      disabled={pending !== null}
      onClick={() =>
        act("open", () => osusu.payoutWindows.open(circleId), "Payout window opened. Members can now vote.")
      }
    >
      Open the next payout window
    </Button>
  );

  return (
    <div className="space-y-4 rounded-xl border border-line p-4">
      {feedback && <Alert tone={feedback.tone}>{feedback.text}</Alert>}

      {!window ? (
        <div className="space-y-3">
          <p className="text-sm text-muted">No payout window has been opened yet.</p>
          {openButton}
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-medium text-ink">Payout window {window.payout_window}</p>
            <Badge tone={STATE[window.state].tone}>{STATE[window.state].label}</Badge>
          </div>

          {window.state === "open" && window.votes_required !== null && (
            <p className="text-sm text-muted">
              {window.votes_cast} of {window.votes_required} required{" "}
              {window.votes_required === 1 ? "vote" : "votes"} cast. Who voted for whom is not shown.
            </p>
          )}

          <ul className="divide-y divide-line text-sm" aria-label="Candidates">
            {window.candidates.map((candidate) => (
              <li key={candidate.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                <span className="text-ink">
                  {candidate.display_name}
                  {candidate.is_you && <span className="text-muted"> (you)</span>}
                  {window.your_vote === candidate.id && (
                    <span className="ml-2 text-brand-800">Your vote</span>
                  )}
                </span>
                <span className="flex items-center gap-2">
                  {window.state !== "open" && (
                    <Badge tone={PAYOUT_STATUS[candidate.status]?.tone}>
                      {PAYOUT_STATUS[candidate.status]?.label ?? candidate.status}
                    </Badge>
                  )}
                  {window.can_vote && (
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={pending === `vote:${candidate.id}`}
                      loadingText="Voting"
                      disabled={pending !== null}
                      onClick={() =>
                        act(
                          `vote:${candidate.id}`,
                          () => osusu.payoutWindows.vote(circleId, window.payout_window, candidate.id),
                          `Your vote for ${candidate.display_name} was recorded.`,
                        )
                      }
                    >
                      Vote for {candidate.display_name}
                    </Button>
                  )}
                </span>
              </li>
            ))}
          </ul>

          {window.state === "open" && !window.can_vote && window.your_vote === null && (
            <p className="text-xs text-muted">You are not eligible to vote in this window.</p>
          )}

          {window.payout && (
            <p className="text-sm text-ink">
              {formatMoney(window.payout.amount)} to {window.payout.recipient}
              {window.payout.paid_at ? `, paid ${formatDate(window.payout.paid_at)}.` : "."}
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            {window.can_approve && (
              <Button
                loading={pending === "approve"}
                loadingText="Approving"
                disabled={pending !== null}
                onClick={() =>
                  act(
                    "approve",
                    () => osusu.payoutWindows.approve(circleId, window.payout_window),
                    "Window approved. The recipient is selected; nothing has been paid yet.",
                  )
                }
              >
                Approve the window
              </Button>
            )}
            {window.can_execute && (
              <Button variant="danger" disabled={pending !== null} onClick={() => setConfirmExecute(true)}>
                {window.state === "failed" ? "Retry the payout" : "Pay out"}
              </Button>
            )}
            {window.state === "paid" && openButton}
          </div>
          {window.state === "processing" && (
            <Alert tone="warning">
              {window.payout?.attempt_state === "submitted"
                ? "The payout provider accepted this payment. It is not paid until settlement is confirmed."
                : "This payment's outcome is being confirmed. It has not failed and must not be paid again."}
            </Alert>
          )}

          <Modal
            open={confirmExecute}
            title={`Pay ${window.payout?.recipient ?? "the recipient"}?`}
            onClose={() => setConfirmExecute(false)}
            footer={
              <div className="flex justify-end gap-2">
                <Button variant="secondary" onClick={() => setConfirmExecute(false)} disabled={pending !== null}>
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  loading={pending === "execute"}
                  loadingText="Paying"
                  onClick={() =>
                    act(
                      "execute",
                      () => osusu.payoutWindows.execute(circleId, window.payout_window),
                      "Payout confirmed by Osusu.",
                    )
                  }
                >
                  Confirm payout
                </Button>
              </div>
            }
          >
            <p>
              Osusu checks the approval and the treasury balance before paying
              {window.payout ? ` ${formatMoney(window.payout.amount)}` : ""}.
            </p>
          </Modal>
        </>
      )}
    </div>
  );
}
