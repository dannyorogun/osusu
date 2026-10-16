import { Card, CardTitle, EmptyState } from "@/components/ui/Surface";
import { formatDate, formatMoney, humanize } from "@/lib/utils/format";
import type { Circle, CircleConstitution } from "@/types/circle";

import { CircleStatusBadge } from "./CircleStatusBadge";

export function CircleOverview({ circle }: { circle: Circle }) {
  return (
    <Card>
      <CardTitle>Overview</CardTitle>
      <dl className="grid gap-4 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-muted">Status</dt>
          <dd className="mt-1"><CircleStatusBadge status={circle.status} /></dd>
        </div>
        <div>
          <dt className="text-muted">Created</dt>
          <dd className="mt-1 text-ink">{formatDate(circle.created_at)}</dd>
        </div>
        <div>
          <dt className="text-muted">Financial lock</dt>
          <dd className="mt-1 text-ink">
            {circle.financial_locked_at ? `Locked ${formatDate(circle.financial_locked_at)}` : "Not locked"}
          </dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-muted">Description</dt>
          <dd className="mt-1 whitespace-pre-line text-ink">
            {circle.description || "No description."}
          </dd>
        </div>
      </dl>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2.5">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right font-medium tabular-nums text-ink">{value}</dd>
    </div>
  );
}

/** Values exactly as stored by the backend; nothing is recalculated. */
export function ConstitutionSection({
  constitution,
}: {
  constitution: CircleConstitution | null;
}) {
  if (!constitution) {
    return (
      <Card>
        <CardTitle>Constitution</CardTitle>
        <p className="text-sm text-muted">No constitution has been recorded for this circle.</p>
      </Card>
    );
  }
  const c = constitution;
  return (
    <Card>
      <CardTitle>Constitution</CardTitle>
      <dl className="divide-y divide-line text-sm">
        <Row label="Contribution" value={`${formatMoney(c.contribution_amount)} ${humanize(c.contribution_frequency).toLowerCase()}`} />
        <Row label="Payout" value={`${formatMoney(c.payout_amount)} ${humanize(c.payout_frequency).toLowerCase()}`} />
        <Row label="Member limit" value={String(c.member_limit)} />
        <Row label="Cycle length" value={`${c.cycle_length} periods`} />
        <Row label="Governance quorum" value={`${c.quorum_percentage}%`} />
        <Row label="Grace period" value={`${c.grace_period_days} days`} />
        <Row label="Reserve" value={c.reserve_enabled ? formatMoney(c.reserve_amount) : "Disabled"} />
        <Row
          label="Member replacement before lock"
          value={c.allow_replacement_before_lock ? "Allowed" : "Not allowed"}
        />
      </dl>
    </Card>
  );
}

/**
 * A circle area whose backend endpoint does not exist yet. Shown honestly
 * instead of with placeholder figures.
 */
export function PendingSection({ title, description }: { title: string; description: string }) {
  return (
    <Card>
      <CardTitle>{title}</CardTitle>
      <EmptyState title="Not available yet" description={description} />
    </Card>
  );
}
