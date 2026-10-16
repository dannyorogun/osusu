import type { Metadata } from "next";

import { CreateCircleForm } from "@/components/circles/CreateCircleForm";
import { PageHeader } from "@/components/ui/Surface";

export const metadata: Metadata = { title: "Create a circle" };

export default function NewCirclePage() {
  return (
    <div className="max-w-3xl">
      <PageHeader
        title="Create a circle"
        description="Set the rules your members will agree to. You'll become the circle's first member."
      />
      <CreateCircleForm />
    </div>
  );
}
