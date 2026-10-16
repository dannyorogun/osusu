"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Alert } from "@/components/ui/Surface";
import { isApiError, userMessage } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-context";
import { safeNextPath } from "@/lib/utils/format";

type Errors = { username?: string; password?: string; form?: string };

export function LoginForm({ next, notice }: { next?: string | null; notice?: string }) {
  const { login } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const found: Errors = {};
    if (!username.trim()) found.username = "Enter your username.";
    if (!password) found.password = "Enter your password.";
    setErrors(found);
    if (Object.keys(found).length) return;

    setSubmitting(true);
    try {
      await login({ username: username.trim(), password });
      router.replace(safeNextPath(next));
    } catch (error) {
      if (isApiError(error) && error.status === 401) {
        setErrors({ form: "That username and password don't match. Please try again." });
      } else if (isApiError(error) && error.kind === "validation") {
        setErrors({
          username: error.fieldMessage("username"),
          password: error.fieldMessage("password"),
          form: error.formMessages[0],
        });
      } else {
        setErrors({ form: userMessage(error) });
      }
      setPassword("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-5">
      {notice && <Alert tone="success">{notice}</Alert>}
      {errors.form && <Alert tone="danger">{errors.form}</Alert>}
      <Input
        label="Username"
        name="username"
        autoComplete="username"
        value={username}
        onChange={(event) => setUsername(event.target.value)}
        error={errors.username}
        hint="Sign in with your username (email sign-in isn't supported yet)."
      />
      <Input
        label="Password"
        name="password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        error={errors.password}
      />
      <Button type="submit" className="w-full" loading={submitting} loadingText="Signing in">
        Sign in
      </Button>
      <p className="text-center text-sm text-muted">
        New to Osusu?{" "}
        <Link href="/register" className="font-medium text-brand-700 hover:underline">
          Create an account
        </Link>
      </p>
    </form>
  );
}
