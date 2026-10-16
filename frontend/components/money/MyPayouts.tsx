"use client";

import Link from "next/link";

import { PAYOUT_STATUS } from "@/components/circles/labels";
import { LoadingBlock } from "@/components/ui/Spinner";
import { Alert, Badge, EmptyState, ErrorState } from "@/components/ui/Surface";
import { Table } from "@/components/ui/Table";
import { useApiResource } from "@/hooks/useApiResource";
import { failedCircles, loadAcrossCircles } from "@/lib/api/across-circles";
import { osusu } from "@/lib/api/endpoints";
import { userMessage } from "@/lib/api/errors";
import { formatDate, formatMoney } from "@/lib/utils/format";

/** Approved and paid payouts in the user's circles, as the backend records them. */
export function MyPayouts() {
  const data = useApiResource(
    () => loadAcrossCircles((circleId) => osusu.circles.payouts(circleId)),
    "payouts",
  );

  if (data.status === "loading") return <LoadingBlock label="Loading payouts" />;
  if (data.status === "error") {
    return (
      <ErrorState
        title="We couldn't load payouts"
        message={userMessage(data.error)}
        onRetry={data.reload}
      />
    );
  }

  const results = data.data.results;
  const rows = results
    .flatMap((result) =>
      result.ok ? result.data.payouts.map((payout) => ({ ...payout, circle: result.circle })) : [],
    )
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  const open = results.flatMap((result) =>
    result.ok ? result.data.open_windows.map((window) => ({ ...window, circle: result.circle })) : [],
  );
  const failed = failedCircles(results);

  return (
    <div className="space-y-4">
      {failed.length > 0 && (
        <Alert tone="warning" title="Some payouts couldn't be loaded.">
          Not shown for: {failed.map((circle) => circle.name).join(", ")}.
        </Alert>
      )}
      {open.map((window) => (
        <p key={`${window.circle.id}:${window.payout_window}`} className="text-sm text-muted">
          {window.circle.name}: payout window {window.payout_window} is open; no recipient approved yet.
        </p>
      ))}
      {rows.length === 0 ? (
        <EmptyState
          title="No payouts yet"
          description="Approved and completed payouts in your circles will appear here."
        />
      ) : (
        <Table
          caption="Payouts in your circles"
          rows={rows}
          rowKey={(row) => row.id}
          columns={[
            {
              key: "circle",
              header: "Circle",
              render: (row) => (
                <Link href={`/circles/${row.circle.id}`} className="hover:underline">
                  {row.circle.name}
                </Link>
              ),
            },
            { key: "window", header: "Window", render: (row) => row.payout_window },
            {
              key: "recipient",
              header: "Recipient",
              render: (row) => (row.is_you ? `${row.recipient} (you)` : row.recipient),
            },
            {
              key: "status",
              header: "Status",
              render: (row) => (
                <Badge tone={PAYOUT_STATUS[row.status]?.tone}>
                  {PAYOUT_STATUS[row.status]?.label ?? row.status}
                </Badge>
              ),
            },
            { key: "paid", header: "Paid on", render: (row) => formatDate(row.paid_at) },
            {
              key: "amount",
              header: "Amount",
              align: "right",
              render: (row) => formatMoney(row.amount),
            },
          ]}
        />
      )}
    </div>
  );
}
