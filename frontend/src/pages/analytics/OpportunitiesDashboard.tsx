import { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis,
} from "recharts";
import ChartCard from "../../components/analytics/ChartCard";
import DataTable from "../../components/analytics/DataTable";
import KpiCard from "../../components/analytics/KpiCard";
import { useAnalyticsFilters } from "../../hooks/useAnalyticsFilters";
import { useAnalyticsQuery } from "../../hooks/useAnalyticsQuery";
import { AZ } from "../../i18n/az";

interface OppsKpis {
  total_deals: number;
  market_p25: number | null;
  median_discount_pct: number | null;
  avg_discount_azn: number | null;
  deals_last_7d: number;
}
interface DealRow {
  id: number; make: string; model: string; year: number | null;
  price_azn: number | null; market_p25: number | null;
  discount_azn: number | null; discount_pct: number | null;
  city: string | null; url: string;
  days_on_market: number | null;
}

const fmtAzn = (v: number | null | undefined) => v != null ? `${Math.round(v).toLocaleString()} AZN` : "—";

const cols: ColumnDef<DealRow, unknown>[] = [
  { accessorKey: "make", header: AZ.cols.make },
  { accessorKey: "model", header: AZ.cols.model },
  { accessorKey: "year", header: AZ.cols.year },
  { accessorKey: "price_azn", header: AZ.cols.price, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "market_p25", header: AZ.cols.marketP25, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "discount_azn", header: AZ.cols.discountAzn, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "discount_pct", header: AZ.cols.discountPct, cell: ({ getValue }) => getValue() != null ? `${getValue()}%` : "—" },
  { accessorKey: "days_on_market", header: AZ.cols.daysOnMarket, cell: ({ getValue }) => getValue() != null ? `${getValue()} gün` : "—" },
  { accessorKey: "city", header: AZ.cols.city },
];

export default function OpportunitiesDashboard() {
  const { toParams } = useAnalyticsFilters();
  const p = toParams();
  const [page, setPage] = useState(0);

  const { data: kpis, loading: kLoading } = useAnalyticsQuery<OppsKpis>("/analytics/opportunities/kpis", p);
  const { data: listings } = useAnalyticsQuery<{ total: number; market_p25: number | null; items: DealRow[] }>(
    "/analytics/opportunities/listings",
    { ...p, offset: page * 50, limit: 50 },
  );

  // Aggregate by make for chart
  const makeMap: Record<string, number> = {};
  for (const row of listings?.items ?? []) {
    makeMap[row.make] = (makeMap[row.make] ?? 0) + 1;
  }
  const makeChart = Object.entries(makeMap)
    .map(([make, count]) => ({ make, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-800">{AZ.dashboards.opportunities}</h1>
      <p className="text-sm text-gray-500">
        Elanlar bazar P25-dən aşağı qiymətləndirilir. Filtrlər eyni qalır — marka, model, il seçin.
      </p>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <KpiCard label={AZ.kpis.totalDeals} value={kpis?.total_deals} tone="good" loading={kLoading} />
        <KpiCard label={AZ.kpis.marketP25} value={kpis?.market_p25} format="azn" loading={kLoading} />
        <KpiCard label={AZ.kpis.medianDiscountPct} value={kpis?.median_discount_pct} format="raw" sub={kpis?.median_discount_pct != null ? `${kpis.median_discount_pct}%` : undefined} tone="good" loading={kLoading} />
        <KpiCard label={AZ.kpis.avgDiscountAzn} value={kpis?.avg_discount_azn} format="azn" tone="good" loading={kLoading} />
        <KpiCard label={AZ.kpis.dealsLast7d} value={kpis?.deals_last_7d} tone="good" loading={kLoading} />
      </div>

      <ChartCard title={AZ.charts.dealsByMake} height={240} empty={!makeChart.length}>
        <BarChart data={makeChart} layout="vertical" margin={{ left: 55, right: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis type="number" tick={{ fontSize: 10 }} />
          <YAxis dataKey="make" type="category" tick={{ fontSize: 10 }} width={50} />
          <Tooltip />
          <Bar dataKey="count" name="Fürsətlər" fill="#16a34a" />
        </BarChart>
      </ChartCard>

      <div className="bg-white rounded-lg border">
        <div className="p-4 border-b">
          <h3 className="font-semibold text-gray-700 text-sm">{AZ.tables.dealListings}</h3>
        </div>
        <div className="p-4">
          <DataTable
            columns={cols}
            data={listings?.items ?? []}
            total={listings?.total}
            pageIndex={page}
            pageSize={50}
            onPageChange={setPage}
            manualPagination
            rowHref={(r) => r.url}
          />
        </div>
      </div>
    </div>
  );
}
