"use client";

import { useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { Spinner } from "@/components/ui/Spinner";
import { Alert, Card, CardTitle, ErrorState } from "@/components/ui/Surface";
import { useApiResource } from "@/hooks/useApiResource";
import { osusu } from "@/lib/api/endpoints";
import { isApiError, userMessage } from "@/lib/api/errors";
import { formatDate, humanize } from "@/lib/utils/format";
import type {
  Circle,
  CircleMember,
  FormationEvaluation,
  InvitationCreated,
} from "@/types/circle";

import { CircleStatusBadge } from "./CircleStatusBadge";
import { CHECK_LABELS } from "./labels";

/**
 * The circle's formation steps: invite, accept the constitution, run the
 * formation checks, financially lock. Every outcome shown here is the
 * backend's response; nothing is assumed to have succeeded. After a
 * successful action the circle (`onChanged`) and member list are reloaded.
 */

const PRE_LOCK = ["draft", "recruiting", "ready"];

/** Runs one action at a time; ignores re-entry while it is in flight. */
function useAction() {
  const busy = useRef(false);
  const [pending, setPending] = useState(false);
  async function run<T>(action: () => Promise<T>): Promise<T | undefined> {
    if (busy.current) return undefined;
    busy.current = true;
    setPending(true);
    try {
      return await action();
    } finally {
      busy.current = false;
      setPending(false);
    }
  }
  return { pending, run };
}

export function CircleWorkflow({
  circle,
  onChanged,
}: {
  circle: Circle;
  onChanged: () => void;
}) {
  const members = useApiResource(
    () => osusu.circles.members(circle.id),
    `workflow-members:${circle.id}`,
    { keepPreviousData: true },
  );
  const refresh = () => {
    members.reload();
    onChanged();
  };

  if (members.status === "loading") {
    return (
      <Card>
        <div className="flex items-center gap-2 text-sm text-muted">
          <Spinner label="Loading circle steps" /> <span aria-hidden="true">Loading…</span>
        </div>
      </Card>
    );
  }
  if (members.status === "error") {
    return (
      <ErrorState
        title="We couldn't load this circle's members"
        message={userMessage(members.error)}
        onRetry={members.reload}
      />
    );
  }

  const me = members.data.find((m) => m.is_you);
  const active = members.data.filter((m) => m.status === "active");
  const isCreator = Boolean(me?.is_creator);

  return (
    <div className="space-y-6">
      <Card>
        <CardTitle>Circle status</CardTitle>
        <p className="flex items-center gap-2 text-sm text-ink">
          <CircleStatusBadge status={circle.status} />
          <span className="text-muted">
            {circle.financial_locked_at
              ? `Financially locked ${formatDate(circle.financial_locked_at)}.`
              : "Reported by Osusu after each step."}
          </span>
        </p>
      </Card>
      <ConstitutionStep circle={circle} me={me} active={active} onDone={refresh} />
      <InviteStep circle={circle} />
      {isCreator ? (
        <>
          <EvaluateStep circle={circle} onDone={refresh} />
          <LockStep circle={circle} onDone={refresh} />
        </>
      ) : (
        <Card>
          <CardTitle>Formation and financial lock</CardTitle>
          <p className="text-sm text-muted">
            Only the circle creator can run the formation checks and lock the circle.
          </p>
        </Card>
      )}
    </div>
  );
}

function ConstitutionStep({
  circle,
  me,
  active,
  onDone,
}: {
  circle: Circle;
  me: CircleMember | undefined;
  active: CircleMember[];
  onDone: () => void;
}) {
  const { pending, run } = useAction();
  const [error, setError] = useState<string | null>(null);
  const accepted = active.filter((m) => m.constitution_accepted).length;

  async function accept() {
    setError(null);
    await run(async () => {
      try {
        await osusu.circles.acceptConstitution(circle.id);
        onDone();
      } catch (caught) {
        setError(userMessage(caught));
      }
    });
  }

  return (
    <Card>
      <CardTitle>Constitution</CardTitle>
      <p className="text-sm text-muted">
        {accepted} of {active.length} active {active.length === 1 ? "member has" : "members have"}{" "}
        accepted the constitution.
      </p>
      {error && <div className="mt-3"><Alert tone="danger">{error}</Alert></div>}
      <div className="mt-4">
        {me?.constitution_accepted ? (
          <p className="text-sm text-ink">
            You accepted the constitution
            {me.constitution_accepted_at ? ` on ${formatDate(me.constitution_accepted_at)}` : ""}.
          </p>
        ) : PRE_LOCK.includes(circle.status) ? (
          <Button onClick={accept} loading={pending} loadingText="Accepting">
            Accept the constitution
          </Button>
        ) : (
          <p className="text-sm text-muted">The constitution can no longer be accepted.</p>
        )}
      </div>
    </Card>
  );
}

function InviteStep({ circle }: { circle: Circle }) {
  const { pending, run } = useAction();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<InvitationCreated | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!email.trim()) {
      setError("Enter the email address of the person you're inviting.");
      return;
    }
    setError(null);
    await run(async () => {
      try {
        setCreated(await osusu.circles.invite(circle.id, email.trim()));
        setEmail("");
      } catch (caught) {
        setError(userMessage(caught));
      }
    });
  }

  if (circle.status !== "recruiting") {
    return (
      <Card>
        <CardTitle>Invitations</CardTitle>
        <p className="text-sm text-muted">
          Invitations are closed while the circle is {humanize(circle.status).toLowerCase()}.
        </p>
      </Card>
    );
  }

  return (
    <Card>
      <CardTitle>Invite someone you trust</CardTitle>
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        {error && <Alert tone="danger">{error}</Alert>}
        <Input
          label="Email address"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          autoComplete="off"
          hint="They must sign in with this email address to accept."
        />
        <Button type="submit" loading={pending} loadingText="Inviting">
          Create invitation
        </Button>
      </form>
      {created && (
        <div className="mt-4">
          <Alert tone="success" title={`Invitation created for ${created.email}.`}>
            Osusu doesn&apos;t send emails yet. Share this code with them; it expires{" "}
            {formatDate(created.expires_at)}.
            <code className="mt-2 block break-all rounded bg-surface px-2 py-1 font-mono text-xs text-ink">
              {created.token}
            </code>
          </Alert>
        </div>
      )}
    </Card>
  );
}

function CheckList({ title, checks }: { title: string; checks: Record<string, boolean> }) {
  return (
    <div>
      <p className="text-sm font-medium text-ink">{title}</p>
      <ul className="mt-2 space-y-1 text-sm">
        {Object.entries(checks).map(([key, passed]) => (
          <li key={key} className={passed ? "text-ink" : "text-red-800"}>
            <span aria-hidden="true">{passed ? "✓" : "✗"}</span>{" "}
            <span className="sr-only">{passed ? "Passed:" : "Failed:"}</span>
            {CHECK_LABELS[key] ?? humanize(key)}
          </li>
        ))}
      </ul>
    </div>
  );
}

function EvaluateStep({ circle, onDone }: { circle: Circle; onDone: () => void }) {
  const { pending, run } = useAction();
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FormationEvaluation | null>(null);
  const canEvaluate = PRE_LOCK.includes(circle.status);

  async function evaluate() {
    setError(null);
    await run(async () => {
      try {
        const evaluation = await osusu.circles.evaluate(circle.id);
        setResult(evaluation);
        if (evaluation.ready) onDone();
      } catch (caught) {
        setResult(null);
        setError(userMessage(caught));
      }
    });
  }

  return (
    <Card>
      <CardTitle>Formation checks</CardTitle>
      <p className="text-sm text-muted">
        Osusu checks membership, constitution acceptance and the circle&apos;s finances. If every
        check passes, the circle becomes Ready.
      </p>
      {error && <div className="mt-3"><Alert tone="danger">{error}</Alert></div>}
      {result && (
        <div className="mt-4 space-y-4">
          <Alert
            tone={result.ready ? "success" : "warning"}
            title={result.ready ? "All checks passed. The circle is Ready." : "Not ready yet."}
          />
          <CheckList title="Formation" checks={result.formation_checks} />
          {result.financial_checks && (
            <CheckList title="Finances" checks={result.financial_checks.checks} />
          )}
          {result.cash_flow && (
            <CheckList
              title="Cash flow"
              checks={{ cash_flow_valid: result.cash_flow.passed }}
            />
          )}
        </div>
      )}
      <div className="mt-4">
        {canEvaluate ? (
          <Button variant="secondary" onClick={evaluate} loading={pending} loadingText="Checking">
            Run formation checks
          </Button>
        ) : (
          <p className="text-sm text-muted">Formation has already been completed.</p>
        )}
      </div>
    </Card>
  );
}

function LockStep({ circle, onDone }: { circle: Circle; onDone: () => void }) {
  const { pending, run } = useAction();
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [failed, setFailed] = useState<Record<string, boolean> | null>(null);
  const [locked, setLocked] = useState(false);

  async function lock() {
    setError(null);
    setFailed(null);
    await run(async () => {
      try {
        await osusu.circles.lock(circle.id);
        setConfirming(false);
        setLocked(true);
        onDone();
      } catch (caught) {
        setConfirming(false);
        setError(userMessage(caught));
        const checks = isApiError(caught) ? caught.details.checks : undefined;
        if (checks && typeof checks === "object") {
          setFailed(checks as Record<string, boolean>);
        }
      }
    });
  }

  if (!PRE_LOCK.includes(circle.status)) {
    return (
      <Card>
        <CardTitle>Financial lock</CardTitle>
        <p className="text-sm text-ink">
          {circle.financial_locked_at
            ? `The circle was financially locked on ${formatDate(circle.financial_locked_at)}.`
            : "The circle is past the financial lock."}
        </p>
      </Card>
    );
  }

  return (
    <Card>
      <CardTitle>Financial lock</CardTitle>
      <p className="text-sm text-muted">
        Locking commits every member to the constitution. It can&apos;t be undone. Osusu checks
        every requirement again before locking.
      </p>
      {locked && <div className="mt-3"><Alert tone="success" title="The circle is financially locked." /></div>}
      {error && <div className="mt-3"><Alert tone="danger">{error}</Alert></div>}
      {failed && <div className="mt-3"><CheckList title="Requirements" checks={failed} /></div>}
      <div className="mt-4">
        {circle.status === "ready" ? (
          <Button variant="danger" onClick={() => setConfirming(true)} disabled={pending}>
            Financially lock the circle
          </Button>
        ) : (
          <p className="text-sm text-muted">
            Available once the formation checks pass and the circle is Ready.
          </p>
        )}
      </div>
      <Modal
        open={confirming}
        title="Financially lock this circle?"
        onClose={() => setConfirming(false)}
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setConfirming(false)} disabled={pending}>
              Cancel
            </Button>
            <Button variant="danger" onClick={lock} loading={pending} loadingText="Locking">
              Lock circle
            </Button>
          </div>
        }
      >
        <p>This is permanent. Members can no longer join or change the constitution.</p>
      </Modal>
    </Card>
  );
}
