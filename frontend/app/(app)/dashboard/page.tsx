"use client";

import Link from "next/link";

import { describeActivity } from "@/components/circles/labels";
import { ButtonLink } from "@/components/ui/Button";
import { LoadingBlock } from "@/components/ui/Spinner";
import {
  Card,
  CardTitle,
  EmptyState,
  ErrorState,
  PageHeader,
  StatCard,
} from "@/components/ui/Surface";
import { useApiResource } from "@/hooks/useApiResource";
import {
  type AcrossCircles,
  failedCircles,
  loadAcrossCircles,
} from "@/lib/api/across-circles";
import { osusu } from "@/lib/api/endpoints";
import { userMessage } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-context";
import { formatDate, formatMoney } from "@/lib/utils/format";
import type { ActivityEvent } from "@/types/circle";

const RECENT_ACTIVITY = 8;

/**
 * Real data only: counts of what the backend returned, the user's own
 * open obligations, and supported circle activity. Nothing is summed or
 * estimated here.
 */
export default function DashboardPage() {
  const { currentUser } = useAuth();
  const name = currentUser?.first_name || currentUser?.username;

  return (
    <>
      <PageHeader
        title={name ? `Welcome, ${name}` : "Welcome"}
        description="Your circles, contributions and activity at a glance."
        actions={<ButtonLink href="/circles/new">Create a circle</ButtonLink>}
      />
      <DashboardSummary />
      <div className="mt-8 grid gap-6 lg:grid-cols-2">
        <RecentActivity />
        <Card>
          <CardTitle>Getting started</CardTitle>
          <ol className="list-decimal space-y-2 pl-5 text-sm text-muted">
            <li>Create a circle and set the rules everyone will agree to.</li>
            <li>Invite people you already know and trust.</li>
            <li>Each member accepts the constitution before money moves.</li>
          </ol>
          <div className="mt-5 flex flex-wrap gap-2">
            <ButtonLink href="/circles/new">Create a circle</ButtonLink>
            <ButtonLink href="/circles" variant="secondary">Accept an invitation</ButtonLink>
          </div>
        </Card>
      </div>
    </>
  );
}

function DashboardSummary() {
  const data = useApiResource(
    () => Promise.all([osusu.circles.list(), osusu.users.obligations()]),
    "dashboard-summary",
  );

  if (data.status === "loading") return <LoadingBlock label="Loading your summary" />;
  if (data.status === "error") {
    return (
      <ErrorState
        title="We couldn't load your summary"
        message={userMessage(data.error)}
        onRetry={data.reload}
      />
    );
  }

  const [circles, obligations] = data.data;
  // Already ordered by due date by the backend.
  const open = obligations.filter((o) => o.status === "pending" || o.status === "overdue");
  const next = open[0];

  return (
    <section aria-label="Summary" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard label="Circles" value={circles.length} />
      <StatCard
        label="Active circles"
        value={circles.filter((circle) => circle.status === "active").length}
      />
      <StatCard
        label="Contributions due"
        value={open.length}
        note={open.some((o) => o.status === "overdue") ? "Includes overdue contributions" : undefined}
      />
      <StatCard
        label="Next contribution"
        value={next ? formatMoney(next.amount_due) : "None due"}
        note={next ? `${next.circle.name} · due ${formatDate(next.due_date)}` : undefined}
      />
    </section>
  );
}

function RecentActivity() {
  const data = useApiResource(
    () => loadAcrossCircles((circleId) => osusu.circles.activity(circleId)),
    "dashboard-activity",
  );

  return (
    <Card>
      <CardTitle>Recent activity</CardTitle>
      {data.status === "loading" && <LoadingBlock label="Loading activity" />}
      {data.status === "error" && (
        <ErrorState
          title="We couldn't load activity"
          message={userMessage(data.error)}
          onRetry={data.reload}
        />
      )}
      {data.status === "success" && <ActivityList {...data.data} />}
    </Card>
  );
}

function ActivityList({ results }: AcrossCircles<ActivityEvent[]>) {
  const events = results
    .flatMap((result) =>
      result.ok ? result.data.map((event) => ({ event, circle: result.circle })) : [],
    )
    .sort((a, b) => b.event.occurred_at.localeCompare(a.event.occurred_at))
    .slice(0, RECENT_ACTIVITY);
  const failed = failedCircles(results);

  return (
    <>
      {events.length === 0 ? (
        <EmptyState
          title="No activity to show yet"
          description="Activity from your circles will appear here."
        />
      ) : (
        <ol className="divide-y divide-line text-sm">
          {events.map(({ event, circle }) => (
            <li key={event.id} className="py-2.5">
              <p className="text-ink">{describeActivity(event)}</p>
              <p className="mt-0.5 text-xs text-muted">
                <Link href={`/circles/${circle.id}`} className="hover:underline">
                  {circle.name}
                </Link>{" "}
                · {formatDate(event.occurred_at)}
              </p>
            </li>
          ))}
        </ol>
      )}
      {failed.length > 0 && (
        <p className="mt-3 text-xs text-muted">
          Activity couldn&apos;t be loaded for: {failed.map((circle) => circle.name).join(", ")}.
        </p>
      )}
    </>
  );
}
