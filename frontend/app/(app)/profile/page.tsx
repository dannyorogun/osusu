"use client";

import { Avatar } from "@/components/ui/Avatar";
import { Badge, Card, CardTitle, PageHeader } from "@/components/ui/Surface";
import { useAuth } from "@/lib/auth/auth-context";
import { formatDate } from "@/lib/utils/format";

export default function ProfilePage() {
  const { currentUser } = useAuth();
  if (!currentUser) return null; // RequireAuth renders nothing else

  const fullName = [currentUser.first_name, currentUser.last_name].filter(Boolean).join(" ");

  return (
    <div className="max-w-2xl">
      <PageHeader title="Profile" description="Your Osusu account." />
      <Card>
        <div className="flex items-center gap-4">
          <Avatar
            firstName={currentUser.first_name}
            lastName={currentUser.last_name}
            username={currentUser.username}
          />
          <div className="min-w-0">
            <p className="truncate font-semibold text-ink">{fullName || currentUser.username}</p>
            <p className="truncate text-sm text-muted">{currentUser.email}</p>
          </div>
        </div>
      </Card>
      <Card className="mt-6">
        <CardTitle>Account details</CardTitle>
        <dl className="divide-y divide-line text-sm">
          {[
            ["Username", currentUser.username],
            ["Email", currentUser.email],
            ["Member since", formatDate(currentUser.created_at)],
          ].map(([label, value]) => (
            <div key={label} className="flex justify-between gap-4 py-2.5">
              <dt className="text-muted">{label}</dt>
              <dd className="truncate text-ink">{value}</dd>
            </div>
          ))}
          <div className="flex justify-between gap-4 py-2.5">
            <dt className="text-muted">Verification</dt>
            <dd>
              {currentUser.is_verified ? (
                <Badge tone="success">Verified</Badge>
              ) : (
                <Badge tone="warning">Not verified</Badge>
              )}
            </dd>
          </div>
        </dl>
        <p className="mt-4 text-xs text-muted">Profile editing isn&apos;t available yet.</p>
      </Card>
    </div>
  );
}
