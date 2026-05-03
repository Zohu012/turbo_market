import { useCallback, useEffect, useRef, useState } from "react";
import api from "../api/client";

interface QueryState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

// Module-level cache: key → { data, ts }
const _cache = new Map<string, { data: unknown; ts: number }>();
const SESSION_TTL_MS = 60_000; // 60 s per-tab cache

function cacheKey(endpoint: string, params: Record<string, unknown>): string {
  return endpoint + "?" + new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== null && v !== "")
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => [k, String(v)])
  ).toString();
}

export function useAnalyticsQuery<T>(
  endpoint: string,
  params: Record<string, unknown>,
  opts?: { skip?: boolean },
): QueryState<T> & { refetch: () => void } {
  const [state, setState] = useState<QueryState<T>>({ data: null, loading: true, error: null });
  const abortRef = useRef<AbortController | null>(null);
  const key = cacheKey(endpoint, params);
  const keyRef = useRef(key);
  keyRef.current = key;

  const fetch = useCallback(() => {
    if (opts?.skip) {
      setState({ data: null, loading: false, error: null });
      return;
    }

    // Check module cache
    const cached = _cache.get(key);
    if (cached && Date.now() - cached.ts < SESSION_TTL_MS) {
      setState({ data: cached.data as T, loading: false, error: null });
      return;
    }

    // Cancel previous
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    setState((s) => ({ ...s, loading: true, error: null }));

    api
      .get<T>(endpoint, {
        params: Object.fromEntries(
          Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""),
        ),
        signal: ctrl.signal,
      })
      .then((r) => {
        if (keyRef.current !== key) return; // stale
        _cache.set(key, { data: r.data, ts: Date.now() });
        setState({ data: r.data, loading: false, error: null });
      })
      .catch((err) => {
        if (err?.code === "ERR_CANCELED") return;
        setState({ data: null, loading: false, error: err?.response?.data?.detail ?? err?.message ?? "Xəta" });
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, opts?.skip]);

  useEffect(() => {
    fetch();
    return () => abortRef.current?.abort();
  }, [fetch]);

  return { ...state, refetch: fetch };
}
