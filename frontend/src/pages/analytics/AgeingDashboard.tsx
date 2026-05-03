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

interface AgeingKpis {
  over_30d: number;
  over_60d: number;
  over_90d: number;
  avg_days_over_30d: number | null;
  value_tied_over_60d_azn: number | null;
  median_price_ageing: number | null;
  median_price_fresh: number | null;
}
interface AgeingRow {
  id: number; make: string; model: string; year: number | null;
  price_azn: number | null; city: string | null; url: string;
  days_on_market: number | null;
}

const fmtAzn = (v: number | null | undefined) => v != null ? `${Math.round(v).toLocaleString()} AZN` : "—";

const cols: ColumnDef<AgeingRow, unknown>[] = [
  { accessorKey: "make", header: AZ.cols.make },
  { accessorKey: "model", header: AZ.cols.model },
  { accessorKey: "year", header: AZ.cols.year },
  { accessorKey: "days_on_market", header: AZ.cols.daysOnMarket, cell: ({ getValue }) => getValue() != null ? `${getValue()} gün` : "—" },
  { accessorKey: "price_azn", header: AZ.cols.price, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "city", header: AZ.cols.city },
];

export default function AgeingDashboard() {
  const { toParams } = useAnalyticsFilters();
  const p = toParams();
  const [page, setPage] = useState(0);
  const [threshold, setThreshold] = useState(30);

  const { data: kpis, loading: kLoading } = useAnalyticsQuery<AgeingKpis>("/analytics/ageing/kpis", p);
  const { data: dist } = useAnalyticsQuery<Array<{ range: string; count: number }>>("/analytics/ageing/distribution", p);
  const { data: byMake } = useAnalyticsQuery<Array<{ make: string; count: number }>>("/analytics/ageing/by-make", p);
  const { data: listings } = useAnalyticsQuery<{ total: number; items: AgeingRow[] }>(
    "/analytics/ageing/listings",
    { ...p, threshold, offset: page * 50, limit: 50 },
  );

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-800">{AZ.dashboards.ageing}</h1>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-3">
        <KpiCard label={AZ.kpis.over30d} value={kpis?.over_30d} tone="warn" loading={kLoading} />
        <KpiCard label={AZ.kpis.over60d} value={kpis?.over_60d} tone="warn" loading={kLoading} />
        <KpiCard label={AZ.kpis.over90d} value={kpis?.over_90d} tone="bad" loading={kLoading} />
        <KpiCard label={AZ.kpis.avgDaysOver30} value={kpis?.avg_days_over_30d} format="days" loading={kLoading} />
        <KpiCard label={AZ.kpis.valueTiedOver60} value={kpis?.value_tied_over_60d_azn} format="azn" loading={kLoading} />
        <KpiCard label="Med. köhnə qiymət" value={kpis?.median_price_ageing} format="azn" loading={kLoading} />
        <KpiCard label="Med. təzə qiymət" value={kpis?.median_price_fresh} format="azn" tone="good" loading={kLoading} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title={AZ.charts.ageDistribution} height={240} empty={!dist?.length}>
          <BarChart data={dist ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="range" tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}g`} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip />
            <Bar dataKey="count" name="Elanlar" fill="#f59e0b" />
          </BarChart>
        </ChartCard>

        <ChartCard title={AZ.charts.ageingByMake} height={240} empty={!byMake?.length}>
          <BarChart data={byMake ?? []} layout="vertical" margin={{ left: 55, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} />
            <YAxis dataKey="make" type="category" tick={{ fontSize: 10 }} width={50} />
            <Tooltip />
            <Bar dataKey="count" name="Say" fill="#ef4444" />
          </BarChart>
        </ChartCard>
      </div>

      <div className="bg-white rounded-lg border">
        <div className="p-4 border-b flex items-center gap-4">
          <h3 className="font-semibold text-gray-700 text-sm">{AZ.tables.ageingListings}</h3>
          <label className="text-sm text-gray-500 flex items-center gap-2 ml-auto">
            Minimum gün:
            <select
              value={threshold}
              onChange={(e) => { setThreshold(Number(e.target.value)); setPage(0); }}
              className="border rounded px-2 py-1 text-sm"
            >
              {[14, 30, 60, 90, 120].map((v) => (
                <option key={v} value={v}>{v}g</option>
              ))}
            </select>
          </label>
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
