"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button, ButtonLink } from "@/components/ui/Button";
import { Checkbox, Input, Select, Textarea } from "@/components/ui/Field";
import { Alert, Card, CardTitle } from "@/components/ui/Surface";
import { osusu } from "@/lib/api/endpoints";
import { isApiError, userMessage } from "@/lib/api/errors";
import type { CreateCircleRequest } from "@/types/circle";

/**
 * Fields and minimums mirror circles.serializers.CreateCircleSerializer
 * (UX only - the backend validates everything again). Amounts are sent as
 * decimal strings; nothing here computes financial values.
 */

export type CreateCircleValues = {
  name: string;
  description: string;
  member_limit: string;
  contribution_amount: string;
  contribution_frequency: string;
  payout_amount: string;
  payout_frequency: string;
  cycle_length: string;
  quorum_percentage: string;
  grace_period_days: string;
  reserve_enabled: boolean;
  reserve_amount: string;
  allow_replacement_before_lock: boolean;
};

type TextField = Exclude<keyof CreateCircleValues, "reserve_enabled" | "allow_replacement_before_lock">;
export type CreateCircleErrors = Partial<Record<keyof CreateCircleValues | "form", string>>;

export const INITIAL_VALUES: CreateCircleValues = {
  name: "",
  description: "",
  member_limit: "",
  contribution_amount: "",
  contribution_frequency: "weekly", // backend default
  payout_amount: "",
  payout_frequency: "biweekly", // backend default
  cycle_length: "",
  quorum_percentage: "",
  grace_period_days: "",
  reserve_enabled: false, // backend default
  reserve_amount: "0.00",
  allow_replacement_before_lock: true, // backend default
};

// The backend stores frequency as free text; these are the values it uses.
const FREQUENCIES = [
  { value: "weekly", label: "Weekly" },
  { value: "biweekly", label: "Every two weeks" },
  { value: "monthly", label: "Monthly" },
] as const;

const MONEY = /^\d{1,8}(\.\d{1,2})?$/; // max_digits=10, decimal_places=2
const INTEGER = /^\d+$/;

function integerIn(value: string, min: number, max?: number): boolean {
  if (!INTEGER.test(value)) return false;
  const n = Number(value);
  return n >= min && (max === undefined || n <= max);
}

function moneyAtLeast(value: string, min: "0" | "0.01"): boolean {
  if (!MONEY.test(value)) return false;
  return min === "0" || /[1-9]/.test(value); // > 0 without float arithmetic
}

export function validateCreateCircle(v: CreateCircleValues): CreateCircleErrors {
  const e: CreateCircleErrors = {};
  if (!v.name.trim()) e.name = "Give your circle a name.";
  else if (v.name.trim().length > 120) e.name = "Use 120 characters or fewer.";
  if (!integerIn(v.member_limit, 2, 100)) e.member_limit = "Enter a whole number from 2 to 100.";
  if (!moneyAtLeast(v.contribution_amount, "0.01")) {
    e.contribution_amount = "Enter an amount such as 50 or 50.00.";
  }
  if (!moneyAtLeast(v.payout_amount, "0.01")) {
    e.payout_amount = "Enter an amount such as 100 or 100.00.";
  }
  if (!integerIn(v.cycle_length, 1)) e.cycle_length = "Enter a whole number of at least 1.";
  if (!integerIn(v.quorum_percentage, 1, 100)) {
    e.quorum_percentage = "Enter a percentage from 1 to 100.";
  }
  if (!integerIn(v.grace_period_days, 0)) {
    e.grace_period_days = "Enter a whole number of days (0 or more).";
  }
  if (!moneyAtLeast(v.reserve_amount, "0")) e.reserve_amount = "Enter an amount such as 0 or 25.00.";
  return e;
}

export function toRequest(v: CreateCircleValues): CreateCircleRequest {
  return {
    name: v.name.trim(),
    description: v.description.trim(),
    member_limit: Number(v.member_limit),
    contribution_amount: v.contribution_amount,
    contribution_frequency: v.contribution_frequency,
    payout_amount: v.payout_amount,
    payout_frequency: v.payout_frequency,
    cycle_length: Number(v.cycle_length),
    quorum_percentage: Number(v.quorum_percentage),
    grace_period_days: Number(v.grace_period_days),
    reserve_enabled: v.reserve_enabled,
    reserve_amount: v.reserve_amount,
    allow_replacement_before_lock: v.allow_replacement_before_lock,
  };
}

export function CreateCircleForm() {
  const router = useRouter();
  const [values, setValues] = useState<CreateCircleValues>(INITIAL_VALUES);
  const [errors, setErrors] = useState<CreateCircleErrors>({});
  const [submitting, setSubmitting] = useState(false);

  const text = (field: TextField) => ({
    name: field,
    value: values[field],
    error: errors[field],
    onChange: (event: { target: { value: string } }) =>
      setValues((current) => ({ ...current, [field]: event.target.value })),
  });

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const found = validateCreateCircle(values);
    setErrors(found);
    if (Object.keys(found).length) return;

    setSubmitting(true);
    try {
      const circle = await osusu.circles.create(toRequest(values));
      router.push(`/circles/${circle.id}?created=1`);
    } catch (error) {
      if (isApiError(error) && error.kind === "validation") {
        const fromServer: CreateCircleErrors = { form: error.formMessages[0] };
        for (const field of Object.keys(INITIAL_VALUES) as Array<keyof CreateCircleValues>) {
          const message = error.fieldMessage(field);
          if (message) fromServer[field] = message;
        }
        if (!Object.values(fromServer).some(Boolean)) fromServer.form = userMessage(error);
        setErrors(fromServer);
      } else {
        setErrors({ form: userMessage(error) });
      }
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-6">
      {errors.form && <Alert tone="danger">{errors.form}</Alert>}

      <Card>
        <CardTitle>About the circle</CardTitle>
        <div className="space-y-5">
          <Input label="Circle name" maxLength={120} {...text("name")} />
          <Textarea label="Description" hint="Optional. What are you saving towards?" {...text("description")} />
          <Input label="Member limit" inputMode="numeric" hint="Between 2 and 100 members." {...text("member_limit")} />
        </div>
      </Card>

      <Card>
        <CardTitle>Money</CardTitle>
        <div className="grid gap-5 sm:grid-cols-2">
          <Input label="Contribution amount (£)" inputMode="decimal" {...text("contribution_amount")} />
          <Select label="Contribution frequency" options={FREQUENCIES} {...text("contribution_frequency")} />
          <Input label="Payout amount (£)" inputMode="decimal" {...text("payout_amount")} />
          <Select label="Payout frequency" options={FREQUENCIES} {...text("payout_frequency")} />
          <Input label="Cycle length" inputMode="numeric" hint="Number of periods in one cycle." {...text("cycle_length")} />
        </div>
        <p className="mt-4 text-xs text-muted">
          Osusu checks the circle&apos;s financial consistency before it can be locked.
        </p>
      </Card>

      <Card>
        <CardTitle>Governance and safeguards</CardTitle>
        <div className="grid gap-5 sm:grid-cols-2">
          <Input label="Quorum (%)" inputMode="numeric" hint="Share of members needed for a decision." {...text("quorum_percentage")} />
          <Input label="Grace period (days)" inputMode="numeric" hint="Days allowed after a contribution is due." {...text("grace_period_days")} />
        </div>
        <div className="mt-5 space-y-4">
          <Checkbox
            label="Keep a reserve"
            checked={values.reserve_enabled}
            onChange={(event) => setValues((c) => ({ ...c, reserve_enabled: event.target.checked }))}
          />
          <Input label="Reserve amount (£)" inputMode="decimal" {...text("reserve_amount")} />
          <Checkbox
            label="Allow member replacement before the financial lock"
            checked={values.allow_replacement_before_lock}
            onChange={(event) =>
              setValues((c) => ({ ...c, allow_replacement_before_lock: event.target.checked }))
            }
          />
        </div>
      </Card>

      <div className="flex flex-wrap justify-end gap-2">
        <ButtonLink href="/circles" variant="secondary">Cancel</ButtonLink>
        <Button type="submit" loading={submitting} loadingText="Creating circle">
          Create circle
        </Button>
      </div>
    </form>
  );
}
