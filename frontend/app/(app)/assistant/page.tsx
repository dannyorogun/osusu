import type { Metadata } from "next";

import { Alert, Card, PageHeader } from "@/components/ui/Surface";

export const metadata: Metadata = { title: "Assistant" };

/**
 * The assistant is disabled by the backend readiness gate. This page never
 * produces answers itself; questions are asked per circle (circle page →
 * Assistant tab), where the backend's 503 is shown as "unavailable".
 */
export default function AssistantPage() {
  return (
    <div className="max-w-2xl">
      <PageHeader
        title="Osusu Assistant"
        description="Ask questions about your circle, contributions, payouts and activity."
      />
      <Alert tone="info" title="AI assistance is currently unavailable.">
        The assistant will be switched on once it has been fully validated.
      </Alert>
      <Card className="mt-6">
        <p className="text-sm text-muted">
          When available, the assistant explains your circle&apos;s own records and cites
          them. It is informational only: it can&apos;t move money, approve payouts or
          change votes.
        </p>
      </Card>
    </div>
  );
}
