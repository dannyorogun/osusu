"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { Alert } from "@/components/ui/Surface";
import { osusu } from "@/lib/api/endpoints";
import { userMessage } from "@/lib/api/errors";

/** Join a circle with an invitation code (the backend decides validity). */
export function AcceptInvitation() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!token.trim()) {
      setError("Paste the invitation code you were sent.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await osusu.circles.acceptInvitation(token.trim());
      router.push(`/circles/${result.circle_id}?joined=1`);
    } catch (caught) {
      setError(userMessage(caught));
      setSubmitting(false);
    }
  }

  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)}>
        Accept an invitation
      </Button>
      <Modal open={open} title="Accept an invitation" onClose={() => setOpen(false)}>
        <form onSubmit={onSubmit} noValidate className="space-y-4">
          <p>Only accept invitations from people you know and trust.</p>
          {error && <Alert tone="danger">{error}</Alert>}
          <Input
            label="Invitation code"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            autoComplete="off"
          />
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
            <Button type="submit" loading={submitting} loadingText="Joining">
              Join circle
            </Button>
          </div>
        </form>
      </Modal>
    </>
  );
}
