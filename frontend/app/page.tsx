import { Logo } from "@/components/layout/Logo";
import { ButtonLink } from "@/components/ui/Button";

const PRINCIPLES = [
  {
    title: "Agreed rules",
    body: "Every circle runs on a constitution its members accept before any money moves.",
  },
  {
    title: "Transparent records",
    body: "Contributions, payouts and treasury come from an immutable ledger, not a spreadsheet.",
  },
  {
    title: "Trust first",
    body: "Invite people you know. Trust is earned cycle by cycle, together.",
  },
];

export default function Home() {
  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-5 sm:px-6">
        <Logo />
        <nav className="flex gap-2">
          <ButtonLink href="/login" variant="ghost">Sign in</ButtonLink>
          <ButtonLink href="/register">Get started</ButtonLink>
        </nav>
      </header>

      <main className="mx-auto max-w-6xl px-4 pb-20 pt-12 sm:px-6 sm:pt-20">
        <p className="text-sm font-medium text-brand-700">Community savings circles</p>
        <h1 className="mt-3 max-w-3xl text-4xl font-semibold tracking-tight text-ink sm:text-5xl">
          Trust your circle before you start a circle.
        </h1>
        <p className="mt-5 max-w-2xl text-lg text-muted">
          Osusu helps friends, families and communities save together in rotating
          circles, with clear rules, fair payouts and records everyone can rely on.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <ButtonLink href="/register">Create an account</ButtonLink>
          <ButtonLink href="/login" variant="secondary">I already have an account</ButtonLink>
        </div>

        <ul className="mt-16 grid gap-4 sm:grid-cols-3">
          {PRINCIPLES.map((item) => (
            <li key={item.title} className="rounded-xl border border-line bg-surface p-6">
              <p className="font-semibold text-ink">{item.title}</p>
              <p className="mt-2 text-sm text-muted">{item.body}</p>
            </li>
          ))}
        </ul>
      </main>
    </div>
  );
}
