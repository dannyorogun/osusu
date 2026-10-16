import type { Metadata } from "next";

import { MyPayouts } from "@/components/money/MyPayouts";
import { PageHeader } from "@/components/ui/Surface";

export const metadata: Metadata = { title: "Payouts" };

export default function PayoutsPage() {
  return (
    <>
      <PageHeader
        title="Payouts"
        description="Payout eligibility and order are decided by each circle's rules and votes."
      />
      <MyPayouts />
    </>
  );
}
