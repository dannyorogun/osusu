import { Badge } from "@/components/ui/Surface";
import type { CircleStatus } from "@/types/circle";

const STATUS: Record<CircleStatus, { label: string; tone: "neutral" | "brand" | "success" | "warning" | "info" }> = {
  draft: { label: "Draft", tone: "neutral" },
  recruiting: { label: "Recruiting", tone: "info" },
  ready: { label: "Ready", tone: "brand" },
  locked: { label: "Financially locked", tone: "warning" },
  active: { label: "Active", tone: "success" },
  completed: { label: "Completed", tone: "neutral" },
};

export function CircleStatusBadge({ status }: { status: CircleStatus | string }) {
  const known = STATUS[status as CircleStatus];
  return <Badge tone={known?.tone ?? "neutral"}>{known?.label ?? status}</Badge>;
}
