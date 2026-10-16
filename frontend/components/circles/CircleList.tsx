import Link from "next/link";

import { EmptyState } from "@/components/ui/Surface";
import { ButtonLink } from "@/components/ui/Button";
import { formatMoney, humanize } from "@/lib/utils/format";
import type { MyCircle } from "@/types/circle";

import { CircleStatusBadge } from "./CircleStatusBadge";

/** Renders circles exactly as the backend returns them. */
export function CircleList({ circles }: { circles: ReadonlyArray<MyCircle> }) {
  if (circles.length === 0) {
    return (
      <EmptyState
        title="You haven't joined a circle yet."
        description="Create your own circle or accept an invitation from someone you trust."
        action={<ButtonLink href="/circles/new">Create a circle</ButtonLink>}
      />
    );
  }

  return (
    <ul className="grid gap-4 md:grid-cols-2">
      {circles.map((circle) => (
        <li key={circle.id}>
          <Link
            href={`/circles/${circle.id}`}
            className="block rounded-xl border border-line bg-surface p-5 transition-colors hover:border-brand-200"
          >
            <div className="flex items-start justify-between gap-3">
              <p className="min-w-0 truncate font-semibold text-ink">{circle.name}</p>
              <CircleStatusBadge status={circle.status} />
            </div>
            {circle.constitution && (
              <p className="mt-3 text-sm text-muted">
                {formatMoney(circle.constitution.contribution_amount)}{" "}
                {humanize(circle.constitution.contribution_frequency).toLowerCase()} ·
                {circle.member_count} of {circle.constitution.member_limit} members
              </p>
            )}
          </Link>
        </li>
      ))}
    </ul>
  );
}
