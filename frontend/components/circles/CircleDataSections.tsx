"use client";

import type { ReactNode } from "react";

import { Spinner } from "@/components/ui/Spinner";
import { Alert, Badge, Card, CardTitle, EmptyState, ErrorState } from "@/components/ui/Surface";
import { Table } from "@/components/ui/Table";
import { useApiResource, type ResourceState } from "@/hooks/useApiResource";
import { osusu } from "@/lib/api/endpoints";
import { userMessage } from "@/lib/api/errors";
import { formatDate, formatMoney } from "@/lib/utils/format";
import type { LedgerTransactionType } from "@/types/circle";

import { PayoutWindowPanel } from "./PayoutWindowPanel";
import {
  MEMBER_STATUS,
  OBLIGATION_STATUS,
  PAYOUT_STATUS,
  describeActivity,
} from "./labels";

/**
 * Circle sections backed by their own endpoints. Each loads and fails on
 * its own: one unavailable section never blanks the page. Every figure is
 * shown exactly as the backend returned it.
 */

function Section<T>({
  title,
  resource,
  children,
}: {
  title: string;
  resource: ResourceState<T> & { reload: () => void };
  children: (data: T) => ReactNode;
}) {
  return (
    <Card>
      <CardTitle>{title}</CardTitle>
      {resource.status === "loading" && (
        <div className="flex items-center gap-2 py-6 text-sm text-muted">
          <Spinner label={`Loading ${title.toLowerCase()}`} />
          <span aria-hidden="true">Loading {title.toLowerCase()}…</span>
        </div>
      )}
      {resource.status === "error" && (
        <ErrorState
          title={`We couldn't load ${title.toLowerCase()}`}
          message={userMessage(resource.error)}
          onRetry={resource.reload}
        />
      )}
      {resource.status === "success" && children(resource.data)}
    </Card>
  );
}

export function MembersSection({ circleId }: { circleId: string }) {
  const members = useApiResource(() => osusu.circles.members(circleId), `members:${circleId}`);
  return (
    <Section title="Members" resource={members}>
      {(rows) =>
        rows.length === 0 ? (
          <EmptyState title="No members to show" />
        ) : (
          <Table
            caption="Circle members"
            rows={rows}
            rowKey={(row) => row.id}
            columns={[
              {
                key: "name",
                header: "Member",
                render: (row) => (
                  <span>
                    {row.display_name}
                    {row.is_you && <span className="text-muted"> (you)</span>}
                    {row.is_creator && <span className="text-muted"> · creator</span>}
                  </span>
                ),
              },
              {
                key: "status",
                header: "Status",
                render: (row) => (
                  <Badge tone={MEMBER_STATUS[row.status]?.tone}>
                    {MEMBER_STATUS[row.status]?.label ?? row.status}
                  </Badge>
                ),
              },
              { key: "joined", header: "Joined", render: (row) => formatDate(row.joined_at) },
              {
                key: "constitution",
                header: "Constitution",
                render: (row) => (row.constitution_accepted ? "Accepted" : "Not yet accepted"),
              },
            ]}
          />
        )
      }
    </Section>
  );
}

export function ObligationsSection({ circleId }: { circleId: string }) {
  const obligations = useApiResource(
    () => osusu.circles.obligations(circleId),
    `obligations:${circleId}`,
  );
  return (
    <Section title="Your contributions" resource={obligations}>
      {(rows) =>
        rows.length === 0 ? (
          <EmptyState
            title="No contributions due yet"
            description="Contributions are scheduled by Osusu once the circle starts its periods."
          />
        ) : (
          <>
            <Table
              caption="Your contribution obligations"
              rows={rows}
              rowKey={(row) => row.id}
              columns={[
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
            <p className="mt-3 text-xs text-muted">
              Only your own contributions are shown. A contribution is marked paid only when the
              payment provider confirms it.
            </p>
          </>
        )
      }
    </Section>
  );
}

export function PayoutsSection({ circleId }: { circleId: string }) {
  const payouts = useApiResource(() => osusu.circles.payouts(circleId), `payouts:${circleId}`, {
    keepPreviousData: true,
  });
  return (
    <Section title="Payouts" resource={payouts}>
      {(data) => (
        <div className="space-y-4">
          <PayoutWindowPanel circleId={circleId} onChanged={payouts.reload} />
          <p className="text-sm font-medium text-ink">Payout history</p>
          {data.payouts.length === 0 ? (
            <EmptyState
              title="No payouts yet"
              description="Approved and completed payouts will appear here."
            />
          ) : (
            <Table
              caption="Payout history"
              rows={data.payouts}
              rowKey={(row) => row.id}
              columns={[
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
      )}
    </Section>
  );
}

const LEDGER_LABELS: Array<[LedgerTransactionType, string]> = [
  ["contribution", "Contributions"],
  ["payout", "Payouts"],
  ["refund", "Refunds"],
  ["reserve", "Reserve"],
  ["adjustment", "Adjustments (incoming)"],
  ["adjustment_out", "Adjustments (outgoing)"],
  ["payout_return", "Payout returns"],
];

export function TreasurySection({ circleId }: { circleId: string }) {
  const treasury = useApiResource(() => osusu.circles.treasury(circleId), `treasury:${circleId}`);
  return (
    <Section title="Treasury" resource={treasury}>
      {(data) => (
        <div className="space-y-4">
          <div>
            <p className="text-sm text-muted">Balance</p>
            <p className="mt-1 text-3xl font-semibold tracking-tight text-ink tabular-nums">
              {formatMoney(data.balance)}
            </p>
            <p className="mt-1 text-xs text-muted">
              Calculated by Osusu from {data.completed_transaction_count} completed ledger{" "}
              {data.completed_transaction_count === 1 ? "transaction" : "transactions"}.
            </p>
          </div>
          <dl className="divide-y divide-line text-sm">
            {LEDGER_LABELS.map(([type, label]) => {
              const total = data.totals[type];
              return (
                <div key={type} className="flex items-baseline justify-between gap-4 py-2.5">
                  <dt className="text-muted">
                    {label} ({total?.count ?? 0})
                  </dt>
                  <dd className="font-medium tabular-nums text-ink">{formatMoney(total?.total)}</dd>
                </div>
              );
            })}
          </dl>
          {Number(data.reserved_for_payouts) > 0 && (
            <p className="text-xs text-muted">
              {formatMoney(data.reserved_for_payouts)} is reserved for a payout whose payment is being
              confirmed; {formatMoney(data.available_balance)} is available.
            </p>
          )}
          {(data.pending_transaction_count > 0 || data.failed_transaction_count > 0) && (
            <p className="text-xs text-muted">
              Not included in the balance: {data.pending_transaction_count} pending and{" "}
              {data.failed_transaction_count} failed{" "}
              {data.pending_transaction_count + data.failed_transaction_count === 1
                ? "transaction"
                : "transactions"}
              .
            </p>
          )}
        </div>
      )}
    </Section>
  );
}

export function ActivitySection({ circleId }: { circleId: string }) {
  const activity = useApiResource(() => osusu.circles.activity(circleId), `activity:${circleId}`);
  return (
    <Section title="Activity" resource={activity}>
      {(events) =>
        events.length === 0 ? (
          <EmptyState title="No activity recorded yet" />
        ) : (
          <ol className="divide-y divide-line text-sm">
            {events.map((event) => (
              <li key={event.id} className="flex items-baseline justify-between gap-4 py-2.5">
                <span className="text-ink">{describeActivity(event)}</span>
                <time className="shrink-0 text-muted" dateTime={event.occurred_at}>
                  {formatDate(event.occurred_at)}
                </time>
              </li>
            ))}
          </ol>
        )
      }
    </Section>
  );
}

export function TrustSection({ circleId }: { circleId: string }) {
  const trust = useApiResource(() => osusu.circles.trust(circleId), `trust:${circleId}`);
  return (
    <Section title="Trust" resource={trust}>
      {(data) => (
        <div className="space-y-5 text-sm">
          <Alert tone="info" title="No trust score is shown.">
            <ul className="mt-1 list-disc space-y-1 pl-5">
              {data.score_unavailable_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </Alert>

          <div>
            <p className="font-medium text-ink">Your contribution record</p>
            {data.data_status === "insufficient_data" ? (
              <p className="mt-1 text-muted">
                Not enough history yet: none of your contributions has been paid or become overdue.
                This is not a sign of low trust.
              </p>
            ) : null}
            <dl className="mt-2 divide-y divide-line">
              {[
                ["Paid in this circle", data.your_record_in_circle.paid],
                ["Overdue in this circle", data.your_record_in_circle.overdue],
                ["Due in this circle", data.your_record_in_circle.pending],
                ["Paid across your circles", data.your_history.paid_contributions],
                ["Overdue across your circles", data.your_history.overdue_contributions],
                ["Circles you completed", data.your_history.completed_circles],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-4 py-2">
                  <dt className="text-muted">{label}</dt>
                  <dd className="font-medium tabular-nums text-ink">{value}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-2 text-xs text-muted">Only you can see your record.</p>
          </div>

          <p className="text-muted">
            {data.circle.active_members} active{" "}
            {data.circle.active_members === 1 ? "member" : "members"} ·{" "}
            {data.circle.invitation_connections} invitation{" "}
            {data.circle.invitation_connections === 1 ? "connection" : "connections"} between
            members.
          </p>
        </div>
      )}
    </Section>
  );
}
