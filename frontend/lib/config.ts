/**
 * Public (browser-visible) configuration. Everything here is inlined into
 * client bundles at build time, so it must never contain secrets.
 */

function required(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(
      `${name} is not configured. Copy .env.example to .env.local ` +
        "or set it in the deployment environment.",
    );
  }
  return value.replace(/\/+$/, "");
}

/** Django API origin used by the browser, e.g. https://api.osusu.example */
export function apiBaseUrl(): string {
  // Referenced literally so Next.js can inline it at build time.
  return required("NEXT_PUBLIC_API_URL", process.env.NEXT_PUBLIC_API_URL);
}
