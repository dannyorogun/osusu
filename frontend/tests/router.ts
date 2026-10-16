import { vi } from "vitest";

/** Shared spy standing in for Next's router in every test. */
export const router = {
  push: vi.fn(),
  replace: vi.fn(),
  back: vi.fn(),
  refresh: vi.fn(),
  prefetch: vi.fn(),
};

export const navigation = {
  pathname: "/dashboard",
  searchParams: new URLSearchParams(),
  params: {} as Record<string, string>,
};
