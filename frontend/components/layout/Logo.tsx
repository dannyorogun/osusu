import Link from "next/link";

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="inline-flex items-center gap-2 font-semibold tracking-tight text-ink">
      <span
        aria-hidden="true"
        className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-700 text-sm font-bold text-white"
      >
        O
      </span>
      <span className="text-lg">Osusu</span>
    </Link>
  );
}
