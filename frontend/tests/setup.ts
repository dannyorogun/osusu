import "@testing-library/jest-dom/vitest";

import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { navigation, router } from "./router";

// The default 1 s for findBy*/waitFor was occasionally exceeded when the
// whole suite runs in parallel on a busy machine (a timing flake, not a
// behaviour difference). Assertions are unchanged.
configure({ asyncUtilTimeout: 3000 });

afterEach(() => {
  cleanup();
  Object.values(router).forEach((spy) => spy.mockReset());
  navigation.pathname = "/dashboard";
  navigation.searchParams = new URLSearchParams();
  navigation.params = {};
});

// Next.js navigation is mocked at the boundary.
vi.mock("next/navigation", async () => {
  const shared = await import("./router");
  return {
    useRouter: () => shared.router,
    usePathname: () => shared.navigation.pathname,
    useSearchParams: () => shared.navigation.searchParams,
    useParams: () => shared.navigation.params,
  };
});
