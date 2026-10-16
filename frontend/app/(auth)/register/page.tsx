import type { Metadata } from "next";

import { RegisterForm } from "@/components/auth/RegisterForm";

export const metadata: Metadata = { title: "Create account" };

export default function RegisterPage() {
  return (
    <>
      <h1 className="text-xl font-semibold text-ink">Create your account</h1>
      <p className="mb-6 mt-1 text-sm text-muted">
        Save together with people you trust.
      </p>
      <RegisterForm />
    </>
  );
}
