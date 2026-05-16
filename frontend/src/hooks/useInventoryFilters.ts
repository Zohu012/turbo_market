import { useCallback, useMemo, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import type { Filters } from "../components/FilterBar";

const FILTER_KEYS: Array<keyof Filters> = [
  "make", "model", "year_min", "year_max", "body_type", "fuel_type", "transmission",
  "engine_min", "engine_max", "hp_min", "hp_max", "color", "condition", "market_for", "is_new",
  "city", "price_min", "price_max", "odometer_min", "odometer_max",
  "seller_type", "is_credit", "is_barter", "is_on_order",
  "date_added_from", "date_added_to", "date_sold_from", "date_sold_to",
  "days_to_sell_min", "days_to_sell_max", "status", "sort_by", "sort_dir", "features",
];

const DEFAULTS: Partial<Filters> = {
  status: "active",
  sort_by: "date_added",
  sort_dir: "desc",
};

export function useInventoryFilters() {
  const [searchParams, setSearchParams] = useSearchParams();
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const filters: Filters = useMemo(() => {
    const f: Partial<Filters> = {};
    for (const key of FILTER_KEYS) {
      f[key] = searchParams.get(key) ?? (DEFAULTS[key] ?? "");
    }
    return f as Filters;
  }, [searchParams]);

  const setFilters = useCallback(
    (partial: Partial<Filters>, immediate = false) => {
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

  const toParams = useCallback(
    (extra?: Record<string, unknown>) => ({
      ...Object.fromEntries(
        Object.entries(filters).filter(([, v]) => v !== "" && v !== undefined),
      ),
      ...extra,
    }),
    [filters],
  );

  return { filters, setFilters, resetFilters, toParams };
}
