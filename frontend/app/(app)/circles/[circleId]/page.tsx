"use client";

import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AssistantPanel } from "@/components/circles/AssistantPanel";
import {
  ActivitySection,
  MembersSection,
  ObligationsSection,
  PayoutsSection,
  TreasurySection,
  TrustSection,
} from "@/components/circles/CircleDataSections";
import { CircleWorkflow } from "@/components/circles/CircleWorkflow";
import { CircleOverview, ConstitutionSection } from "@/components/circles/CircleSections";
import { CircleStatusBadge } from "@/components/circles/CircleStatusBadge";
import { ButtonLink } from "@/components/ui/Button";
import { LoadingBlock } from "@/components/ui/Spinner";
import { Alert, ErrorState, PageHeader } from "@/components/ui/Surface";
import { useApiResource } from "@/hooks/useApiResource";
import { osusu } from "@/lib/api/endpoints";
import { isApiError, userMessage } from "@/lib/api/errors";
import { cn } from "@/lib/utils/format";

const TABS = [
  { id: "overview", title: "Overview" },
  { id: "constitution", title: "Constitution" },
  { id: "manage", title: "Set up" },
  { id: "members", title: "Members" },
  { id: "contributions", title: "Contributions" },
  { id: "payouts", title: "Payouts" },
  { id: "treasury", title: "Treasury" },
  { id: "activity", title: "Activity" },
  { id: "trust", title: "Trust" },
  { id: "assistant", title: "Assistant" },
] as const;

type TabId = (typeof TABS)[number]["id"];

function CircleDetail() {
  const { circleId } = useParams<{ circleId: string }>();
  const params = useSearchParams();
  const [tab, setTab] = useState<TabId>("overview");
  // Kept on screen while reloading after a workflow action.
  const circle = useApiResource(() => osusu.circles.get(circleId), circleId, {
    keepPreviousData: true,
  });

  if (circle.status === "loading") return <LoadingBlock label="Loading circle" />;

  if (circle.status === "error") {
    const notFound = isApiError(circle.error) && [403, 404].includes(circle.error.status);
    return (
      <ErrorState
        title={notFound ? "Circle not available" : "We couldn't load this circle"}
        message={
          notFound
            ? "This circle doesn't exist or you're not an active member of it."
            : userMessage(circle.error)
        }
        onRetry={notFound ? undefined : circle.reload}
      />
    );
  }

  const data = circle.data;

  return (
    <>
      <PageHeader
        title={data.name}
        description="Figures on this page come from Osusu's records."
        actions={<CircleStatusBadge status={data.status} />}
      />
      {params.get("created") && (
        <div className="mb-6">
          <Alert tone="success" title="Circle created.">
            Invite people you trust, then agree the constitution together.
          </Alert>
        </div>
      )}
      {params.get("joined") && (
        <div className="mb-6">
          <Alert tone="success" title="You've joined this circle." />
        </div>
      )}

      <div className="-mx-4 mb-6 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <div role="tablist" aria-label="Circle sections" className="flex min-w-max gap-1 border-b border-line">
          {TABS.map((item) => (
            <button
              key={item.id}
              role="tab"
              type="button"
              id={`tab-${item.id}`}
              aria-selected={tab === item.id}
              aria-controls="circle-panel"
              onClick={() => setTab(item.id)}
              className={cn(
                "min-h-11 border-b-2 px-3 text-sm font-medium",
                tab === item.id
                  ? "border-brand-700 text-brand-800"
                  : "border-transparent text-muted hover:text-ink",
              )}
            >
              {item.title}
            </button>
          ))}
        </div>
      </div>

      <div id="circle-panel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {tab === "overview" && <CircleOverview circle={data} />}
        {tab === "constitution" && <ConstitutionSection constitution={data.constitution} />}
        {tab === "members" && <MembersSection circleId={data.id} />}
        {tab === "contributions" && <ObligationsSection circleId={data.id} />}
        {tab === "payouts" && <PayoutsSection circleId={data.id} />}
        {tab === "treasury" && <TreasurySection circleId={data.id} />}
        {tab === "activity" && <ActivitySection circleId={data.id} />}
        {tab === "manage" && <CircleWorkflow circle={data} onChanged={circle.reload} />}
        {tab === "trust" && <TrustSection circleId={data.id} />}
        {tab === "assistant" && <AssistantPanel circleId={data.id} />}
      </div>

      <div className="mt-8">
        <ButtonLink href="/circles" variant="ghost">← Back to circles</ButtonLink>
      </div>
    </>
  );
}

export default function CircleDetailPage() {
  return (
    <Suspense fallback={<LoadingBlock label="Loading circle" />}>
      <CircleDetail />
    </Suspense>
  );
}
