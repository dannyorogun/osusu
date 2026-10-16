import type { Metadata } from "next";

import { EmptyState, PageHeader } from "@/components/ui/Surface";

export const metadata: Metadata = { title: "Trust" };

export default function TrustPage() {
  return (
    <>
      <PageHeader
        title="Trust"
        description="Trust your circle before you start a circle."
      />
      <EmptyState
        title="Your trust network will appear here"
        description="Trust grows each time you complete a cycle with people you invited or were invited by."
      />
    </>
  );
}
