import { useCallback, useMemo, useRef } from "react";
import { useSearchParams } from "react-router-dom";

export interface AnalyticsFilters {
  // Vehicle
  make?: string;
  model?: string;
  year_min?: string;
  year_max?: string;
  condition?: string;
  body_type?: string;
  fuel_type?: string;
  transmission?: string;
  drive_type?: string;
  engine_min?: string;
  engine_max?: string;
  hp_min?: string;
  hp_max?: string;
  odometer_min?: string;
  odometer_max?: string;
  color?: string;
  market_for?: string;
  // Market
  city?: string;
  price_min?: string;
  price_max?: string;
  currency?: string;
  credit?: string;
  barter?: string;
  seller_type?: string;
  status?: string;
  date_from?: string;
  date_to?: string;
  features?: string; // comma-separated IDs
}

const FILTER_KEYS: Array<keyof AnalyticsFilters> = [
  "make", "model", "year_min", "year_max", "condition", "body_type",
  "fuel_type", "transmission", "drive_type", "engine_min", "engine_max",
  "hp_min", "hp_max", "odometer_min", "odometer_max", "color", "market_for",
  "city", "price_min", "price_max", "currency", "credit", "barter",
  "seller_type", "status", "date_from", "date_to", "features",
];

export function useAnalyticsFilters() {
  const [searchParams, setSearchParams] = useSearchParams();
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const filters: AnalyticsFilters = useMemo(() => {
    const f: AnalyticsFilters = {};
    for (const key of FILTER_KEYS) {
      const v = searchParams.get(key);
      if (v !== null && v !== "") (f as Record<string, string>)[key] = v;
    }
    return f;
  }, [searchParams]);

  const setFilters = useCallback(
    (partial: Partial<AnalyticsFilters>, immediate = false) => {
      const apply = () => {
        setSearchParams((prev) => {
          const next = new URLSearchParams(prev);
          for (const [key, value] of Object.entries(partial)) {
            if (value === "" || value === undefined || value === null) {
              next.delete(key);
            } else {
              next.set(key, String(value));
            }
          }
          // Cascade: clear model when make changes
          if ("make" in partial && partial.make !== prev.get("make")) {
            next.delete("model");
          }
          return next;
        });
      };

      if (immediate) {
        apply();
      } else {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(apply, 250);
      }
    },
    [setSearchParams],
  );

  const resetFilters = useCallback(() => {
    setSearchParams(new URLSearchParams());
  }, [setSearchParams]);

  /** Convert filters to a plain object suitable for axios params. */
  const toParams = useCallback(
    (extra?: Record<string, unknown>) => ({
      ...Object.fromEntries(
        Object.entries(filters).filter(([, v]) => v !== undefined && v !== ""),
      ),
      ...extra,
    }),
    [filters],
  );

  /** Human-readable one-liner summary for the collapsed filter bar. */
  const summary = useMemo(() => {
    const parts: string[] = [];
    if (filters.make) parts.push(filters.make + (filters.model ? ` ${filters.model}` : ""));
    if (filters.year_min || filters.year_max)
      parts.push(`${filters.year_min ?? ""}–${filters.year_max ?? ""}`);
    if (filters.city) parts.push(filters.city);
    const extras =
      FILTER_KEYS.filter(
        (k) => filters[k] && !["make", "model", "year_min", "year_max", "city"].includes(k),
      ).length;
    if (extras > 0) parts.push(`+${extras} filtr`);
    return parts.length ? parts.join(" · ") : null;
  }, [filters]);

  const hasFilters = FILTER_KEYS.some((k) => !!filters[k]);

  return { filters, setFilters, resetFilters, toParams, summary, hasFilters };
}
