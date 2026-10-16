"use client";

import { LoadingBlock } from "@/components/ui/Spinner";
import { ErrorState } from "@/components/ui/Surface";
import { useApiResource } from "@/hooks/useApiResource";
import { osusu } from "@/lib/api/endpoints";
import { userMessage } from "@/lib/api/errors";

import { CircleList } from "./CircleList";

/** The signed-in user's circles (ACTIVE memberships), from GET /api/circles/. */
export function MyCircles() {
  const circles = useApiResource(() => osusu.circles.list(), "my-circles");

  if (circles.status === "loading") return <LoadingBlock label="Loading your circles" />;
  if (circles.status === "error") {
    return (
      <ErrorState
        title="We couldn't load your circles"
        message={userMessage(circles.error)}
        onRetry={circles.reload}
      />
    );
  }
  return <CircleList circles={circles.data} />;
}
