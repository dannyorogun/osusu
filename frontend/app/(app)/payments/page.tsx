import type { Metadata } from "next";

import { MyPayments } from "@/components/money/MyPayments";
import { PageHeader } from "@/components/ui/Surface";

export const metadata: Metadata = { title: "Payments" };

export default function PaymentsPage() {
  return (
    <>
      <PageHeader
        title="Payments"
        description="Your contributions as Osusu records them. A contribution is marked paid only when the payment provider confirms it, never by this page."
      />
      <MyPayments />
    </>
  );
}
