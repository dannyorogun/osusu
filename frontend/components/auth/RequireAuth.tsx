"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { LoadingBlock } from "@/components/ui/Spinner";
import { useAuth } from "@/lib/auth/auth-context";

/**
 * Client-side guard for app pages (UX only). Django authorizes every
 * request; this just avoids rendering an empty shell to signed-out users.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [isAuthenticated, isLoading, pathname, router]);

  if (isLoading || !isAuthenticated) {
    return (
      <div className="mx-auto max-w-md p-10">
        <LoadingBlock label="Checking your session" />
      </div>
    );
  }

  return <>{children}</>;
}
