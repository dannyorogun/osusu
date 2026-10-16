import { cn, initials } from "@/lib/utils/format";

/** Member representation: initials only, no external image requests. */
export function Avatar({
  firstName,
  lastName,
  username,
  size = "md",
}: {
  firstName: string;
  lastName: string;
  username: string;
  size?: "sm" | "md";
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full bg-brand-100 font-semibold text-brand-800",
        size === "sm" ? "h-8 w-8 text-xs" : "h-10 w-10 text-sm",
      )}
    >
      {initials(firstName, lastName, username)}
    </span>
  );
}
