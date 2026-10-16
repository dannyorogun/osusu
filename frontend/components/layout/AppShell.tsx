"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { Avatar } from "@/components/ui/Avatar";
import { useAuth } from "@/lib/auth/auth-context";
import { cn } from "@/lib/utils/format";

import { Logo } from "./Logo";
import { NAV_ITEMS, isActive } from "./nav";

function NavLinks({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  return (
    <ul className="space-y-1">
      {NAV_ITEMS.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex min-h-11 items-center rounded-lg px-3 text-sm font-medium transition-colors",
                active
                  ? "bg-brand-50 text-brand-800"
                  : "text-muted hover:bg-line/40 hover:text-ink",
              )}
            >
              {item.label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function UserMenu() {
  const { currentUser, logout } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape"
        : !ref.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  if (!currentUser) return null;

  async function signOut() {
    setOpen(false);
    await logout();
    router.replace("/login");
  }

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-11 items-center gap-2 rounded-lg px-2 hover:bg-line/40"
      >
        <Avatar
          size="sm"
          firstName={currentUser.first_name}
          lastName={currentUser.last_name}
          username={currentUser.username}
        />
        <span className="hidden text-sm font-medium text-ink sm:inline">
          {currentUser.first_name || currentUser.username}
        </span>
        <span aria-hidden="true" className="text-muted">▾</span>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-40 mt-2 w-56 rounded-xl border border-line bg-surface p-1 shadow-lg"
        >
          <p className="truncate px-3 py-2 text-xs text-muted">{currentUser.email}</p>
          <Link
            role="menuitem"
            href="/profile"
            onClick={() => setOpen(false)}
            className="flex min-h-11 items-center rounded-lg px-3 text-sm hover:bg-canvas"
          >
            Profile
          </Link>
          <button
            role="menuitem"
            type="button"
            onClick={signOut}
            className="flex min-h-11 w-full items-center rounded-lg px-3 text-left text-sm hover:bg-canvas"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur">
        <div className="flex h-16 items-center justify-between gap-3 px-4 sm:px-6">
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="flex h-11 w-11 items-center justify-center rounded-lg hover:bg-line/40 lg:hidden"
              aria-label={menuOpen ? "Close navigation" : "Open navigation"}
              aria-expanded={menuOpen}
              aria-controls="mobile-nav"
              onClick={() => setMenuOpen((value) => !value)}
            >
              <span aria-hidden="true" className="text-xl leading-none">
                {menuOpen ? "×" : "☰"}
              </span>
            </button>
            <Logo href="/dashboard" />
          </div>
          <UserMenu />
        </div>
        {menuOpen && (
          <nav id="mobile-nav" aria-label="Main" className="border-t border-line px-4 py-3 lg:hidden">
            <NavLinks pathname={pathname} onNavigate={() => setMenuOpen(false)} />
          </nav>
        )}
      </header>

      <div className="mx-auto flex max-w-7xl">
        <aside className="hidden w-60 shrink-0 border-r border-line lg:block">
          <nav aria-label="Main" className="sticky top-16 p-4">
            <NavLinks pathname={pathname} />
            <p className="mt-8 px-3 text-xs leading-relaxed text-muted">
              Trust your circle before you start a circle.
            </p>
          </nav>
        </aside>
        <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-10 lg:py-8">{children}</main>
      </div>
    </div>
  );
}
