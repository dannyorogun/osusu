"use client";

import Link from "next/link";

import { OBLIGATION_STATUS } from "@/components/circles/labels";
import { LoadingBlock } from "@/components/ui/Spinner";
import { Badge, EmptyState, ErrorState } from "@/components/ui/Surface";
import { Table } from "@/components/ui/Table";
import { useApiResource } from "@/hooks/useApiResource";
import { osusu } from "@/lib/api/endpoints";
import { userMessage } from "@/lib/api/errors";
import { formatDate, formatMoney } from "@/lib/utils/format";

/**
 * The user's own contribution obligations across their circles, as the
 * backend reports them. There is no "pay" action: no real payment provider
 * is connected, and an obligation is only ever marked paid by the backend
 * after the provider confirms.
 */
export function MyPayments() {
  const data = useApiResource(() => osusu.users.obligations(), "payments");

  if (data.status === "loading") return <LoadingBlock label="Loading your contributions" />;
  if (data.status === "error") {
    return (
      <ErrorState
        title="We couldn't load your contributions"
        message={userMessage(data.error)}
        onRetry={data.reload}
      />
    );
  }

  // Ordered by due date by the backend.
  const rows = data.data;

  if (rows.length === 0) {
    return (
      <EmptyState
        title="No contributions to show yet"
        description="When your circles have contributions scheduled, they'll be listed here."
      />
    );
  }

  return (
    <Table
      caption="Your contributions"
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
        { key: "period", header: "Period", render: (row) => row.period_number },
        { key: "due", header: "Due", render: (row) => formatDate(row.due_date) },
        {
          key: "status",
          header: "Status",
          render: (row) => (
            <Badge tone={OBLIGATION_STATUS[row.status]?.tone}>
              {OBLIGATION_STATUS[row.status]?.label ?? row.status}
            </Badge>
          ),
        },
        { key: "paid", header: "Paid on", render: (row) => formatDate(row.paid_at) },
        {
          key: "amount",
          header: "Amount",
          align: "right",
          render: (row) => formatMoney(row.amount_due),
        },
      ]}
    />
  );
}
