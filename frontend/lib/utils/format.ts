import type { DecimalString, IsoDateTime } from "@/types/api";

/**
 * Display-only formatting. Values come from the backend; nothing here is
 * used for calculation.
 */

const GBP = new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" });

/** "50.00" -> "£50.00". Payments are GBP (payments.Payment.currency). */
export function formatMoney(value: DecimalString | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const amount = Number(value);
  return Number.isFinite(amount) ? GBP.format(amount) : "—";
}

export function formatDate(value: IsoDateTime | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

/** "biweekly" -> "Biweekly"; backend frequencies are free text. */
export function humanize(value: string | null | undefined): string {
  if (!value) return "—";
  const text = value.replace(/[_-]+/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function initials(first: string, last: string, fallback: string): string {
  const letters = `${first.trim().charAt(0)}${last.trim().charAt(0)}`;
  return (letters || fallback.trim().charAt(0) || "?").toUpperCase();
}

/** Only allow same-site relative redirects (prevents open redirects). */
export function safeNextPath(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
    return "/dashboard";
  }
  return value;
}

export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}
