import { useState } from "react";
import { AnalyticsFilters } from "../../hooks/useAnalyticsFilters";
import { AZ } from "../../i18n/az";
import AnalyticsFilterForm from "./AnalyticsFilterForm";

interface Props {
  filters: AnalyticsFilters;
  setFilters: (partial: Partial<AnalyticsFilters>, immediate?: boolean) => void;
  resetFilters: () => void;
  summary: string | null;
  hasFilters: boolean;
}

export default function GlobalFilterBar({
  filters, setFilters, resetFilters, summary, hasFilters,
}: Props) {
  const [open, setOpen] = useState(false);

  return (
    <div className="bg-white rounded-lg border mb-4">
      {/* Header row — always visible */}
      <div className="flex items-center gap-3 px-4 py-2.5">
        <button
          onClick={() => setOpen((v) => !v)}
          className="text-sm font-medium text-blue-600 hover:text-blue-800 flex items-center gap-1.5"
        >
          <span>{open ? "▲" : "▼"}</span>
          {open ? AZ.filters.collapseFilters : AZ.filters.expandFilters}
        </button>

        {!open && summary && (
          <span className="text-sm text-gray-600 truncate">{summary}</span>
        )}

        <div className="flex-1" />

        {hasFilters && (
          <button
            onClick={resetFilters}
            className="text-xs text-red-500 hover:text-red-700 border border-red-200 rounded px-2 py-1 hover:bg-red-50 transition-colors"
          >
            {AZ.filters.reset}
          </button>
        )}
      </div>

      {/* Expanded form */}
      {open && (
        <div className="border-t px-4 pb-4 pt-3">
          <AnalyticsFilterForm filters={filters} setFilters={setFilters} />
        </div>
      )}
    </div>
  );
}
