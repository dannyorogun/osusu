export type NavItem = { href: string; label: string };

export const NAV_ITEMS: ReadonlyArray<NavItem> = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/circles", label: "My Circles" },
  { href: "/payments", label: "Payments" },
  { href: "/payouts", label: "Payouts" },
  { href: "/trust", label: "Trust" },
  { href: "/assistant", label: "Assistant" },
  { href: "/profile", label: "Profile" },
];

export function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}
