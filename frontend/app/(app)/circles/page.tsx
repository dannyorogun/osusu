import type { Metadata } from "next";

import { AcceptInvitation } from "@/components/circles/AcceptInvitation";
import { MyCircles } from "@/components/circles/MyCircles";
import { ButtonLink } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/Surface";

export const metadata: Metadata = { title: "My circles" };

/**
 * Circles where the user is an ACTIVE member. Pending invitations are not
 * memberships yet; they are accepted with their token (AcceptInvitation).
 */
export default function CirclesPage() {
  return (
    <>
      <PageHeader
        title="My circles"
        description="Save together with people you trust."
        actions={
          <>
            <AcceptInvitation />
            <ButtonLink href="/circles/new">Create a circle</ButtonLink>
          </>
        }
      />
      <MyCircles />
    </>
  );
}
