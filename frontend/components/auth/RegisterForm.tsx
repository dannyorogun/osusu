"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Alert } from "@/components/ui/Surface";
import { osusu } from "@/lib/api/endpoints";
import { isApiError, userMessage } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-context";
import type { RegisterRequest } from "@/types/user";

type FieldName = keyof RegisterRequest;
type Errors = Partial<Record<FieldName | "form", string>>;

/** Mirrors the backend rule (RegisterSerializer: min_length=8) for UX only. */
export const MIN_PASSWORD_LENGTH = 8;

const EMPTY: RegisterRequest = {
  email: "",
  username: "",
  first_name: "",
  last_name: "",
  password: "",
};

export function validateRegistration(values: RegisterRequest): Errors {
  const errors: Errors = {};
  if (!values.email.trim()) errors.email = "Enter your email address.";
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email.trim())) {
    errors.email = "Enter a valid email address.";
  }
  if (!values.username.trim()) errors.username = "Choose a username.";
  if (!values.password) errors.password = "Choose a password.";
  else if (values.password.length < MIN_PASSWORD_LENGTH) {
    errors.password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  return errors;
}

export function RegisterForm() {
  const { login } = useAuth();
  const router = useRouter();
  const [values, setValues] = useState<RegisterRequest>(EMPTY);
  const [errors, setErrors] = useState<Errors>({});
  const [submitting, setSubmitting] = useState(false);

  const set = (field: FieldName) => (event: { target: { value: string } }) =>
    setValues((current) => ({ ...current, [field]: event.target.value }));

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const found = validateRegistration(values);
    setErrors(found);
    if (Object.keys(found).length) return;

    const data: RegisterRequest = {
      ...values,
      email: values.email.trim(),
      username: values.username.trim(),
      first_name: values.first_name.trim(),
      last_name: values.last_name.trim(),
    };

    setSubmitting(true);
    try {
      await osusu.users.register(data);
    } catch (error) {
      if (isApiError(error) && error.kind === "validation") {
        setErrors({
          email: error.fieldMessage("email"),
          username: error.fieldMessage("username"),
          first_name: error.fieldMessage("first_name"),
          last_name: error.fieldMessage("last_name"),
          password: error.fieldMessage("password"),
          form: error.formMessages[0],
        });
      } else {
        setErrors({ form: userMessage(error) });
      }
      setSubmitting(false);
      return;
    }

    // Account created: sign straight in; fall back to the login page.
    try {
      await login({ username: data.username, password: data.password });
      router.replace("/dashboard");
    } catch {
      router.replace("/login?registered=1");
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-5">
      {errors.form && <Alert tone="danger">{errors.form}</Alert>}
      <div className="grid gap-5 sm:grid-cols-2">
        <Input label="First name" name="first_name" autoComplete="given-name"
          value={values.first_name} onChange={set("first_name")} error={errors.first_name} />
        <Input label="Last name" name="last_name" autoComplete="family-name"
          value={values.last_name} onChange={set("last_name")} error={errors.last_name} />
      </div>
      <Input label="Email" name="email" type="email" autoComplete="email"
        value={values.email} onChange={set("email")} error={errors.email} />
      <Input label="Username" name="username" autoComplete="username"
        value={values.username} onChange={set("username")} error={errors.username}
        hint="You'll sign in with this." />
      <Input label="Password" name="password" type="password" autoComplete="new-password"
        value={values.password} onChange={set("password")} error={errors.password}
        hint={`At least ${MIN_PASSWORD_LENGTH} characters.`} />
      <Button type="submit" className="w-full" loading={submitting} loadingText="Creating account">
        Create account
      </Button>
      <p className="text-center text-sm text-muted">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-brand-700 hover:underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}
