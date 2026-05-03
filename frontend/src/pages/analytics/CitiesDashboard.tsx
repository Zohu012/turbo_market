import { ColumnDef } from "@tanstack/react-table";
import {
  Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis,
} from "recharts";
import ChartCard from "../../components/analytics/ChartCard";
import DataTable from "../../components/analytics/DataTable";
import KpiCard from "../../components/analytics/KpiCard";
import { useAnalyticsFilters } from "../../hooks/useAnalyticsFilters";
import { useAnalyticsQuery } from "../../hooks/useAnalyticsQuery";
import { AZ } from "../../i18n/az";

interface CitiesKpis {
  cities_tracked: number;
  most_active_city: string | null;
  most_active_count: number;
  highest_median_price_city: string | null;
  fastest_dts_city: string | null;
  fastest_dts_days: number | null;
}
interface CityRow {
  city: string;
  active_count: number;
  share_pct: number | null;
  avg_price: number | null;
  median_price: number | null;
  avg_dts: number | null;
  median_dts: number | null;
}

const fmtAzn = (v: number | null | undefined) => v != null ? `${Math.round(v).toLocaleString()} AZN` : "—";

const cols: ColumnDef<CityRow, unknown>[] = [
  { accessorKey: "city", header: AZ.cols.city },
  { accessorKey: "active_count", header: AZ.cols.count },
  { accessorKey: "share_pct", header: AZ.cols.sharePct, cell: ({ getValue }) => getValue() != null ? `${getValue()}%` : "—" },
  { accessorKey: "median_price", header: AZ.cols.medianPrice, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "avg_price", header: AZ.cols.avgPrice, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "avg_dts", header: AZ.cols.avgDts, cell: ({ getValue }) => getValue() != null ? `${getValue()} gün` : "—" },
  { accessorKey: "median_dts", header: AZ.cols.medianDts, cell: ({ getValue }) => getValue() != null ? `${getValue()} gün` : "—" },
];

export default function CitiesDashboard() {
  const { toParams } = useAnalyticsFilters();
  const p = toParams();

  const { data: kpis, loading: kLoading } = useAnalyticsQuery<CitiesKpis>("/analytics/cities/kpis", p);
  const { data: overview } = useAnalyticsQuery<CityRow[]>("/analytics/cities/overview", p);
  const { data: priceData } = useAnalyticsQuery<Array<{ city: string; median: number | null; avg: number | null; count: number }>>("/analytics/cities/price", p);
  const { data: dtsData } = useAnalyticsQuery<Array<{ city: string; avg_dts: number | null; median_dts: number | null; count: number }>>("/analytics/cities/dts", p);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-800">{AZ.dashboards.cities}</h1>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard label={AZ.kpis.citiesTracked} value={kpis?.cities_tracked} loading={kLoading} />
        <KpiCard label={AZ.kpis.mostActiveCity} value={kpis?.most_active_city} format="raw" loading={kLoading} />
        <KpiCard label="Ən aktiv say" value={kpis?.most_active_count} loading={kLoading} />
        <KpiCard label={AZ.kpis.highestPriceCity} value={kpis?.highest_median_price_city} format="raw" tone="good" loading={kLoading} />
        <KpiCard label={AZ.kpis.fastestDtsCity} value={kpis?.fastest_dts_city} format="raw" tone="good" loading={kLoading} />
        <KpiCard label="Ən sürətli DTS" value={kpis?.fastest_dts_days} format="days" tone="good" loading={kLoading} />
      </div>

      <ChartCard title={AZ.charts.cityCount} height={320} empty={!overview?.length}>
        <BarChart data={(overview ?? []).slice(0, 20)} layout="vertical" margin={{ left: 80, right: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis type="number" tick={{ fontSize: 10 }} />
          <YAxis dataKey="city" type="category" tick={{ fontSize: 10 }} width={75} />
          <Tooltip />
          <Bar dataKey="active_count" name="Aktiv elanlar" fill="#2563eb" />
        </BarChart>
      </ChartCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title={AZ.charts.cityPrice} height={280} empty={!priceData?.length}>
          <BarChart data={priceData ?? []} layout="vertical" margin={{ left: 80, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <YAxis dataKey="city" type="category" tick={{ fontSize: 10 }} width={75} />
            <Tooltip formatter={(v) => fmtAzn(v as number)} />
            <Bar dataKey="median" name="Median" fill="#16a34a" />
          </BarChart>
        </ChartCard>

        <ChartCard title={AZ.charts.cityDts} height={280} empty={!dtsData?.length}>
          <BarChart data={dtsData ?? []} layout="vertical" margin={{ left: 80, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} />
            <YAxis dataKey="city" type="category" tick={{ fontSize: 10 }} width={75} />
            <Tooltip formatter={(v) => [`${v} gün`, "Ort. DTS"]} />
            <Bar dataKey="avg_dts" name="Ort. DTS" fill="#8b5cf6" />
          </BarChart>
        </ChartCard>
      </div>

      <div className="bg-white rounded-lg border">
        <div className="p-4 border-b">
          <h3 className="font-semibold text-gray-700 text-sm">{AZ.tables.cityComparison}</h3>
        </div>
        <div className="p-4">
          <DataTable columns={cols} data={overview ?? []} />
        </div>
      </div>
    </div>
  );
}
