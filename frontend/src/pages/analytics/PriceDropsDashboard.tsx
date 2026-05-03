import { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis,
} from "recharts";
import ChartCard from "../../components/analytics/ChartCard";
import DataTable from "../../components/analytics/DataTable";
import KpiCard from "../../components/analytics/KpiCard";
import { useAnalyticsFilters } from "../../hooks/useAnalyticsFilters";
import { useAnalyticsQuery } from "../../hooks/useAnalyticsQuery";
import { AZ } from "../../i18n/az";

interface PriceDropsKpis {
  total_with_drops: number;
  avg_drop_azn: number | null;
  avg_drop_pct: number | null;
  median_drop_pct: number | null;
  dropped_last_7d: number;
  dropped_last_30d: number;
}
interface DropRow {
  id: number; make: string; model: string; year: number | null;
  price_azn: number | null; old_price: number | null; new_price: number | null;
  drop_azn: number | null; drop_pct: number | null; days_since_drop: number | null;
  city: string | null; url: string;
}

const fmtAzn = (v: number | null | undefined) => v != null ? `${Math.round(v).toLocaleString()} AZN` : "—";

const cols: ColumnDef<DropRow, unknown>[] = [
  { accessorKey: "make", header: AZ.cols.make },
  { accessorKey: "model", header: AZ.cols.model },
  { accessorKey: "year", header: AZ.cols.year },
  { accessorKey: "old_price", header: AZ.cols.oldPrice, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "new_price", header: AZ.cols.newPrice, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "drop_azn", header: AZ.cols.dropAzn, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "drop_pct", header: AZ.cols.dropPct, cell: ({ getValue }) => getValue() != null ? `${getValue()}%` : "—" },
  { accessorKey: "days_since_drop", header: AZ.cols.daysSinceDrop, cell: ({ getValue }) => getValue() != null ? `${getValue()} gün` : "—" },
  { accessorKey: "city", header: AZ.cols.city },
];

export default function PriceDropsDashboard() {
  const { toParams } = useAnalyticsFilters();
  const p = toParams();
  const [page, setPage] = useState(0);

  const { data: kpis, loading: kLoading } = useAnalyticsQuery<PriceDropsKpis>("/analytics/price-drops/kpis", p);
  const { data: dist } = useAnalyticsQuery<Array<{ range: string; count: number }>>("/analytics/price-drops/distribution", p);
  const { data: trend } = useAnalyticsQuery<Array<{ period: string; count: number }>>("/analytics/price-drops/trend", p);
  const { data: byMake } = useAnalyticsQuery<Array<{ make: string; count: number }>>("/analytics/price-drops/by-make", p);
  const { data: recent } = useAnalyticsQuery<{ total: number; items: DropRow[] }>(
    "/analytics/price-drops/recent",
    { ...p, offset: page * 50, limit: 50 },
  );

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-800">{AZ.dashboards.priceDrops}</h1>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard label={AZ.kpis.totalWithDrops} value={kpis?.total_with_drops} loading={kLoading} />
        <KpiCard label={AZ.kpis.avgDropAzn} value={kpis?.avg_drop_azn} format="azn" loading={kLoading} />
        <KpiCard label={AZ.kpis.avgDropPct} value={kpis?.avg_drop_pct} format="raw" sub={kpis?.avg_drop_pct != null ? `${kpis.avg_drop_pct}%` : undefined} loading={kLoading} />
        <KpiCard label={AZ.kpis.medianDropPct} value={kpis?.median_drop_pct} format="raw" sub={kpis?.median_drop_pct != null ? `${kpis.median_drop_pct}%` : undefined} loading={kLoading} />
        <KpiCard label={AZ.kpis.droppedLast7d} value={kpis?.dropped_last_7d} tone="warn" loading={kLoading} />
        <KpiCard label={AZ.kpis.droppedLast30d} value={kpis?.dropped_last_30d} tone="warn" loading={kLoading} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ChartCard title={AZ.charts.dropDistribution} height={240} empty={!dist?.length}>
          <BarChart data={dist ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="range" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip />
            <Bar dataKey="count" name="Elanlar" fill="#ef4444" />
          </BarChart>
        </ChartCard>

        <ChartCard title={AZ.charts.dropTrend} height={240} empty={!trend?.length}>
          <LineChart data={trend ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="period" tick={{ fontSize: 9 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip />
            <Line type="monotone" dataKey="count" name="Say" stroke="#ef4444" dot={false} strokeWidth={2} />
          </LineChart>
        </ChartCard>

        <ChartCard title={AZ.charts.dropsByMake} height={240} empty={!byMake?.length}>
          <BarChart data={byMake ?? []} layout="vertical" margin={{ left: 55, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} />
            <YAxis dataKey="make" type="category" tick={{ fontSize: 10 }} width={50} />
            <Tooltip />
            <Bar dataKey="count" name="Say" fill="#f59e0b" />
          </BarChart>
        </ChartCard>
      </div>

      <div className="bg-white rounded-lg border">
        <div className="p-4 border-b">
          <h3 className="font-semibold text-gray-700 text-sm">{AZ.tables.recentDrops}</h3>
        </div>
        <div className="p-4">
          <DataTable
            columns={cols}
            data={recent?.items ?? []}
            total={recent?.total}
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
