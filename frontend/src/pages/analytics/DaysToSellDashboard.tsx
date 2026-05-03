import { ColumnDef } from "@tanstack/react-table";
import {
  Bar, BarChart, CartesianGrid, Line, LineChart,
  Tooltip, XAxis, YAxis,
} from "recharts";
import ChartCard from "../../components/analytics/ChartCard";
import DataTable from "../../components/analytics/DataTable";
import KpiCard from "../../components/analytics/KpiCard";
import { useAnalyticsFilters } from "../../hooks/useAnalyticsFilters";
import { useAnalyticsQuery } from "../../hooks/useAnalyticsQuery";
import { AZ } from "../../i18n/az";

interface DtsKpis {
  avg_dts: number | null;
  median_dts: number | null;
  fast_threshold_p25: number | null;
  slow_threshold_p75: number | null;
  pct_under_7d: number | null;
  pct_under_30d: number | null;
  total_sold: number;
  ageing_inventory_count: number | null;
}
interface BandRow { band: string; avg_dts: number | null; median_dts: number | null; count: number }
interface MakeModelRow { make: string; model: string; avg_dts: number | null; count: number }
interface VehicleRow {
  id: number; turbo_id: number; make: string; model: string; year: number | null;
  price_azn: number | null; odometer: number | null; city: string | null;
  days_to_sell?: number | null; age_days?: number; url: string;
}

const fmtDays = (v: number | null | undefined) => (v != null ? `${v} gün` : "—");
const fmtAzn = (v: number | null | undefined) => (v != null ? `${Math.round(v).toLocaleString()} AZN` : "—");

const colsMakeModel: ColumnDef<MakeModelRow, unknown>[] = [
  { accessorKey: "make", header: AZ.cols.make },
  { accessorKey: "model", header: AZ.cols.model },
  { accessorKey: "avg_dts", header: AZ.cols.avgDts, cell: ({ getValue }) => fmtDays(getValue() as number) },
  { accessorKey: "median_dts", header: AZ.cols.medianDts, cell: ({ getValue }) => fmtDays(getValue() as number) },
  { accessorKey: "count", header: AZ.cols.count },
];

const colsVehicle: ColumnDef<VehicleRow, unknown>[] = [
  { accessorKey: "make", header: AZ.cols.make },
  { accessorKey: "model", header: AZ.cols.model },
  { accessorKey: "year", header: AZ.cols.year },
  { accessorKey: "price_azn", header: AZ.cols.price, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "odometer", header: AZ.cols.odometer, cell: ({ getValue }) => getValue() != null ? `${(getValue() as number).toLocaleString()} km` : "—" },
  { accessorKey: "city", header: AZ.cols.city },
  { accessorKey: "days_to_sell", header: AZ.cols.daysToSell, cell: ({ getValue }) => fmtDays(getValue() as number) },
];

const colsAgeing: ColumnDef<VehicleRow, unknown>[] = [
  ...colsVehicle.slice(0, 6),
  { accessorKey: "age_days", header: "Aktiv günlər", cell: ({ getValue }) => fmtDays(getValue() as number) },
];

export default function DaysToSellDashboard() {
  const { toParams } = useAnalyticsFilters();
  const p = toParams();

  const { data: kpis, loading: kLoading } = useAnalyticsQuery<DtsKpis>("/analytics/dts/kpis", p);
  const { data: dist } = useAnalyticsQuery<BandRow[]>("/analytics/dts/distribution", p);
  const { data: fastest } = useAnalyticsQuery<MakeModelRow[]>("/analytics/dts/by-make-model", { ...p, order: "fastest", limit: 20 });
  const { data: slowest } = useAnalyticsQuery<MakeModelRow[]>("/analytics/dts/by-make-model", { ...p, order: "slowest", limit: 20 });
  const { data: byYear } = useAnalyticsQuery<BandRow[]>("/analytics/dts/by-year", p);
  const { data: byPriceBand } = useAnalyticsQuery<BandRow[]>("/analytics/dts/by-price-band", p);
  const { data: byCity } = useAnalyticsQuery<BandRow[]>("/analytics/dts/by-city", p);
  const { data: byMileage } = useAnalyticsQuery<BandRow[]>("/analytics/dts/by-mileage-band", p);
  const { data: byBody } = useAnalyticsQuery<BandRow[]>("/analytics/dts/by-body-type", p);
  const { data: bySellerType } = useAnalyticsQuery<BandRow[]>("/analytics/dts/by-seller-type", p);
  const { data: ageingData } = useAnalyticsQuery<{ items: VehicleRow[]; total: number; p75_days: number | null }>("/analytics/dts/active-too-long", p);
  const { data: fastSales } = useAnalyticsQuery<{ items: VehicleRow[]; p25_days: number | null }>("/analytics/dts/recent-fast-sales", p);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-800">{AZ.dashboards.dts}</h1>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-4 gap-3">
        <KpiCard label={AZ.kpis.medianDts} value={kpis?.median_dts} format="days" loading={kLoading} />
        <KpiCard label={AZ.kpis.avgDts} value={kpis?.avg_dts} format="days" loading={kLoading} />
        <KpiCard label={AZ.kpis.fastThreshold} value={kpis?.fast_threshold_p25} format="days" tone="good" loading={kLoading} />
        <KpiCard label={AZ.kpis.slowThreshold} value={kpis?.slow_threshold_p75} format="days" tone="warn" loading={kLoading} />
        <KpiCard label={AZ.kpis.under7d} value={kpis?.pct_under_7d != null ? kpis.pct_under_7d * 100 : null} format="raw" sub={kpis?.pct_under_7d != null ? `${(kpis.pct_under_7d * 100).toFixed(1)}%` : undefined} tone="good" loading={kLoading} />
        <KpiCard label={AZ.kpis.under30d} value={kpis?.pct_under_30d != null ? kpis.pct_under_30d * 100 : null} format="raw" sub={kpis?.pct_under_30d != null ? `${(kpis.pct_under_30d * 100).toFixed(1)}%` : undefined} loading={kLoading} />
        <KpiCard label={AZ.kpis.totalSold} value={kpis?.total_sold} loading={kLoading} />
        <KpiCard label={AZ.kpis.ageingInventory} value={kpis?.ageing_inventory_count} tone="bad" loading={kLoading} />
      </div>

      {/* Distribution */}
      <ChartCard title={AZ.charts.dtsDistribution} height={240} empty={!dist?.length}>
        <BarChart data={dist ?? []}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="lo" tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}g`} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip formatter={(v) => [v, "Elanlar"]} labelFormatter={(v) => `${v} gün`} />
          <Bar dataKey="count" name="Say" fill="#8b5cf6" />
        </BarChart>
      </ChartCard>

      {/* Small charts grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <ChartCard title={AZ.charts.dtsByYear} height={200} empty={!byYear?.length}>
          <BarChart data={byYear ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="year" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip formatter={(v) => [`${v} gün`, "Median"]} />
            <Bar dataKey="median_dts" name="Median gün" fill="#2563eb" />
          </BarChart>
        </ChartCard>

        <ChartCard title={AZ.charts.dtsByPriceBand} height={200} empty={!byPriceBand?.length}>
          <BarChart data={byPriceBand ?? []} layout="vertical" margin={{ left: 55 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} />
            <YAxis dataKey="band" type="category" tick={{ fontSize: 9 }} width={50} />
            <Tooltip formatter={(v) => [`${v} gün`, "Median"]} />
            <Bar dataKey="median_dts" name="Median gün" fill="#16a34a" />
          </BarChart>
        </ChartCard>

        <ChartCard title={AZ.charts.dtsByCity} height={200} empty={!byCity?.length}>
          <BarChart data={(byCity ?? []).slice(0, 12)} layout="vertical" margin={{ left: 60 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} />
            <YAxis dataKey="city" type="category" tick={{ fontSize: 9 }} width={55} />
            <Tooltip formatter={(v) => [`${v} gün`, "Median"]} />
            <Bar dataKey="median_dts" name="Median gün" fill="#f59e0b" />
          </BarChart>
        </ChartCard>

        <ChartCard title={AZ.charts.dtsBySellerType} height={200} empty={!bySellerType?.length}>
          <BarChart data={bySellerType ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="seller_type" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip formatter={(v) => [`${v} gün`, "Median"]} />
            <Bar dataKey="median_dts" name="Median gün" fill="#06b6d4" />
          </BarChart>
        </ChartCard>

        <ChartCard title={AZ.charts.dtsByMileage} height={200} empty={!byMileage?.length}>
          <BarChart data={byMileage ?? []} layout="vertical" margin={{ left: 60 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} />
            <YAxis dataKey="band" type="category" tick={{ fontSize: 9 }} width={55} />
            <Tooltip formatter={(v) => [`${v} gün`, "Median"]} />
            <Bar dataKey="median_dts" name="Median gün" fill="#ef4444" />
          </BarChart>
        </ChartCard>

        <ChartCard title={AZ.charts.dtsByBodyType} height={200} empty={!byBody?.length}>
          <BarChart data={(byBody ?? []).slice(0, 10)} layout="vertical" margin={{ left: 70 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} />
            <YAxis dataKey="body_type" type="category" tick={{ fontSize: 9 }} width={65} />
            <Tooltip formatter={(v) => [`${v} gün`, "Median"]} />
            <Bar dataKey="median_dts" name="Median gün" fill="#8b5cf6" />
          </BarChart>
        </ChartCard>
      </div>

      {/* Tables */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white rounded-lg border p-4">
          <h3 className="font-semibold text-gray-700 text-sm mb-3">{AZ.tables.fastestModels}</h3>
          <DataTable columns={colsMakeModel} data={fastest ?? []} loading={!fastest} />
        </div>
        <div className="bg-white rounded-lg border p-4">
          <h3 className="font-semibold text-gray-700 text-sm mb-3">{AZ.tables.slowestModels}</h3>
          <DataTable columns={colsMakeModel} data={slowest ?? []} loading={!slowest} />
        </div>
      </div>

      <div className="bg-white rounded-lg border p-4">
        <h3 className="font-semibold text-gray-700 text-sm mb-3">
          {AZ.tables.activeTooLong}
          {ageingData?.p75_days != null && (
            <span className="text-gray-400 font-normal ml-1">(P75 = {ageingData.p75_days} gün)</span>
          )}
        </h3>
        <DataTable
          columns={colsAgeing}
          data={ageingData?.items ?? []}
          loading={!ageingData}
          rowHref={(r) => r.url}
        />
      </div>

      <div className="bg-white rounded-lg border p-4">
        <h3 className="font-semibold text-gray-700 text-sm mb-3">
          {AZ.tables.recentFastSales}
          {fastSales?.p25_days != null && (
            <span className="text-gray-400 font-normal ml-1">(P25 = {fastSales.p25_days} gün)</span>
          )}
        </h3>
        <DataTable
          columns={colsVehicle}
          data={fastSales?.items ?? []}
          loading={!fastSales}
          rowHref={(r) => r.url}
        />
      </div>
    </div>
  );
}
