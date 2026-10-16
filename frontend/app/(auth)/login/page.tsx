"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { LoginForm } from "@/components/auth/LoginForm";

function Login() {
  const params = useSearchParams();
  const notice = params.get("registered")
    ? "Your account is ready. Sign in to continue."
    : undefined;

  return (
    <>
      <h1 className="text-xl font-semibold text-ink">Sign in</h1>
      <p className="mb-6 mt-1 text-sm text-muted">Welcome back to your circles.</p>
      <LoginForm next={params.get("next")} notice={notice} />
    </>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <Login />
    </Suspense>
  );
}
