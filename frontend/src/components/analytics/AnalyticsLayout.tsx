import { Outlet } from "react-router-dom";
import { useAnalyticsFilters } from "../../hooks/useAnalyticsFilters";
import AnalyticsSidebar from "./AnalyticsSidebar";
import GlobalFilterBar from "./GlobalFilterBar";

export default function AnalyticsLayout() {
  const { filters, setFilters, resetFilters, summary, hasFilters } = useAnalyticsFilters();

  return (
    <div className="flex gap-6 min-h-full">
      <AnalyticsSidebar />

      <div className="flex-1 min-w-0">
        <GlobalFilterBar
          filters={filters}
          setFilters={setFilters}
          resetFilters={resetFilters}
          summary={summary}
          hasFilters={hasFilters}
        />
        <Outlet />
      </div>
    </div>
  );
}
