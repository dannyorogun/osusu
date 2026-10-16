"use client";

import { useCallback, useEffect, useState } from "react";

export type ResourceState<T> =
  | { status: "loading"; data: null; error: null }
  | { status: "success"; data: T; error: null }
  | { status: "error"; data: null; error: unknown };

type Settled<T> =
  | { request: string; ok: true; data: T }
  | { request: string; ok: false; error: unknown };

/**
 * Loads data on mount (and when `key` changes) with explicit
 * loading / success / error states. `reload()` re-runs the loader.
 * "Loading" is derived: the latest request simply hasn't settled yet.
 */
export function useApiResource<T>(
  load: () => Promise<T>,
  key: string,
  options: {
    /**
     * While a reload() is in flight, keep returning the last successful
     * data (status "success", `refreshing` true) instead of "loading".
     * Used after an action so the page does not blank and remount.
     */
    keepPreviousData?: boolean;
  } = {},
): ResourceState<T> & { reload: () => void; refreshing: boolean } {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const [previous, setPrevious] = useState<{ key: string; data: T } | null>(null);
  const request = `${key}#${attempt}`;

  useEffect(() => {
    let cancelled = false;
    load().then(
      (data) => {
        if (!cancelled) {
          setSettled({ request, ok: true, data });
          setPrevious({ key, data });
        }
      },
      (error: unknown) => {
        if (!cancelled) setSettled({ request, ok: false, error });
      },
    );
    return () => {
      cancelled = true;
    };
    // `load` is identified by `key`; callers pass inline functions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  if (!settled || settled.request !== request) {
    if (options.keepPreviousData && previous && previous.key === key) {
      return { status: "success", data: previous.data, error: null, reload, refreshing: true };
    }
    return { status: "loading", data: null, error: null, reload, refreshing: false };
  }
  return settled.ok
    ? { status: "success", data: settled.data, error: null, reload, refreshing: false }
    : { status: "error", data: null, error: settled.error, reload, refreshing: false };
}
