import type { MyCircle } from "@/types/circle";

import { osusu } from "./endpoints";

export type PerCircle<T> =
  | { circle: MyCircle; ok: true; data: T }
  | { circle: MyCircle; ok: false; error: unknown };

export type AcrossCircles<T> = {
  circles: MyCircle[];
  results: PerCircle<T>[];
};

/**
 * Loads the user's circles, then one circle-scoped resource for each.
 * The circle list failing fails the whole load; a single circle failing
 * is reported for that circle only. The backend does not offer a
 * cross-circle endpoint, so this fans out per circle; nothing is
 * aggregated or calculated here beyond listing what came back.
 */
export async function loadAcrossCircles<T>(
  load: (circleId: string) => Promise<T>,
): Promise<AcrossCircles<T>> {
  const circles = await osusu.circles.list();
  const settled = await Promise.allSettled(circles.map((circle) => load(circle.id)));
  return {
    circles,
    results: settled.map((outcome, index) =>
      outcome.status === "fulfilled"
        ? { circle: circles[index], ok: true, data: outcome.value }
        : { circle: circles[index], ok: false, error: outcome.reason },
    ),
  };
}

export function failedCircles<T>(results: PerCircle<T>[]): MyCircle[] {
  return results.filter((result) => !result.ok).map((result) => result.circle);
}
