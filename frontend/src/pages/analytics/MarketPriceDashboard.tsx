import { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import ChartCard from "../../components/analytics/ChartCard";
import DataTable from "../../components/analytics/DataTable";
import KpiCard from "../../components/analytics/KpiCard";
import { useAnalyticsFilters } from "../../hooks/useAnalyticsFilters";
import { useAnalyticsQuery } from "../../hooks/useAnalyticsQuery";
import { AZ } from "../../i18n/az";

interface PriceKpis {
  avg: number | null; min: number | null; max: number | null;
  stdev: number | null; p10: number | null; p25: number | null;
  median: number | null; p75: number | null; p90: number | null;
  count: number; confidence: string;
}
interface HistBucket { bucket: number; lo: number; hi: number; count: number }
interface BandRow { city?: string; year?: number; seller_type?: string; condition?: string; avg: number | null; median: number | null; count: number }
interface ScatterPoint { id: number; odometer: number; price_azn: number; year: number | null; make: string; model: string }
interface TrendRow { period: string; avg: number | null; median: number | null; count: number }
interface VehicleRow {
  id: number; turbo_id: number; make: string; model: string; year: number | null;
  price_azn: number | null; odometer: number | null; city: string | null; url: string;
  date_deactivated?: string | null; days_to_sell?: number | null;
}
interface OutliersData { lo: number | null; hi: number | null; items: VehicleRow[] }

const fmtAzn = (v: number | null | undefined) => (v != null ? `${Math.round(v).toLocaleString()} AZN` : "—");

const confidenceColor: Record<string, string> = {
  low: "text-red-500", medium: "text-orange-500", high: "text-green-600",
};
const confidenceLabel: Record<string, string> = {
  low: "Aşağı", medium: "Orta", high: "Yüksək",
};

const colsVehicle: ColumnDef<VehicleRow, unknown>[] = [
  { accessorKey: "make", header: AZ.cols.make },
  { accessorKey: "model", header: AZ.cols.model },
  { accessorKey: "year", header: AZ.cols.year },
  { accessorKey: "price_azn", header: AZ.cols.price, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "odometer", header: AZ.cols.odometer, cell: ({ getValue }) => getValue() != null ? `${(getValue() as number).toLocaleString()} km` : "—" },
  { accessorKey: "city", header: AZ.cols.city },
  { accessorKey: "days_to_sell", header: AZ.cols.daysToSell, cell: ({ getValue }) => getValue() != null ? `${getValue()} gün` : "—" },
];

type TableTab = "comparables" | "recent" | "cheapest" | "expensive" | "outliers";

export default function MarketPriceDashboard() {
  const { toParams } = useAnalyticsFilters();
  const p = toParams();
  const [tableTab, setTableTab] = useState<TableTab>("comparables");
  const [comparablesPage, setComparablesPage] = useState(0);

  const { data: kpis, loading: kLoading } = useAnalyticsQuery<PriceKpis>("/analytics/price/kpis", p);
  const { data: hist } = useAnalyticsQuery<{ buckets: HistBucket[]; lo: number | null; hi: number | null }>("/analytics/price/distribution", p);
  const { data: byYear } = useAnalyticsQuery<BandRow[]>("/analytics/price/by-year", p);
  const { data: scatter } = useAnalyticsQuery<ScatterPoint[]>("/analytics/price/vs-mileage", p);
  const { data: trend } = useAnalyticsQuery<TrendRow[]>("/analytics/price/trend", p);
  const { data: byCity } = useAnalyticsQuery<BandRow[]>("/analytics/price/by-city", p);
  const { data: bySellerType } = useAnalyticsQuery<BandRow[]>("/analytics/price/by-seller-type", p);
  const { data: byCondition } = useAnalyticsQuery<BandRow[]>("/analytics/price/by-condition", p);

  const { data: comparables } = useAnalyticsQuery<{ total: number; items: VehicleRow[] }>(
    "/analytics/price/comparables",
    { ...p, offset: comparablesPage * 50, limit: 50 },
    { skip: tableTab !== "comparables" },
  );
  const { data: recent } = useAnalyticsQuery<VehicleRow[]>("/analytics/price/recent-deactivated", p, { skip: tableTab !== "recent" });
  const { data: cheapest } = useAnalyticsQuery<VehicleRow[]>("/analytics/price/cheapest", p, { skip: tableTab !== "cheapest" });
  const { data: expensive } = useAnalyticsQuery<VehicleRow[]>("/analytics/price/most-expensive", p, { skip: tableTab !== "expensive" });
  const { data: outliers } = useAnalyticsQuery<OutliersData>("/analytics/price/outliers", p, { skip: tableTab !== "outliers" });

  const tabItems: Array<{ key: TableTab; label: string }> = [
    { key: "comparables", label: AZ.tables.comparableListings },
    { key: "recent", label: AZ.tables.recentDeactivated },
    { key: "cheapest", label: AZ.tables.cheapest },
    { key: "expensive", label: AZ.tables.mostExpensive },
    { key: "outliers", label: AZ.tables.outliers },
  ];

  const activeTableData = (): VehicleRow[] => {
    if (tableTab === "comparables") return comparables?.items ?? [];
    if (tableTab === "recent") return recent ?? [];
    if (tableTab === "cheapest") return cheapest ?? [];
    if (tableTab === "expensive") return expensive ?? [];
    if (tableTab === "outliers") return outliers?.items ?? [];
    return [];
  };

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-800">{AZ.dashboards.price}</h1>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <KpiCard label={AZ.kpis.medianPrice} value={kpis?.median} format="azn" loading={kLoading} />
        <KpiCard label={AZ.kpis.avgPrice} value={kpis?.avg} format="azn" loading={kLoading} />
        <KpiCard label={AZ.kpis.p10} value={kpis?.p10} format="azn" loading={kLoading} />
        <KpiCard label={AZ.kpis.p90} value={kpis?.p90} format="azn" loading={kLoading} />
        <KpiCard label={AZ.kpis.comparableCount} value={kpis?.count} loading={kLoading} />
        <KpiCard
          label={AZ.kpis.confidence}
          value={kpis?.confidence != null ? confidenceLabel[kpis.confidence] ?? kpis.confidence : null}
          format="raw"
          tone={kpis?.confidence === "high" ? "good" : kpis?.confidence === "low" ? "bad" : "warn"}
          loading={kLoading}
        />
      </div>

      {/* Histogram */}
      <ChartCard title={AZ.charts.priceDistribution} height={240} empty={!hist?.buckets?.length}>
        <BarChart data={hist?.buckets ?? []}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="lo" tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip
            formatter={(v) => [v, "Elanlar"]}
            labelFormatter={(_, pl) => pl[0] ? `${Math.round(pl[0].payload.lo / 1000)}k–${Math.round(pl[0].payload.hi / 1000)}k AZN` : ""}
          />
          <Bar dataKey="count" name="Say" fill="#2563eb" />
        </BarChart>
      </ChartCard>

      {/* Row: by-year + scatter */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title={AZ.charts.priceByYear} height={260} empty={!byYear?.length}>
          <BarChart data={byYear ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="year" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <Tooltip formatter={fmtAzn} />
            <Bar dataKey="median" name="Median" fill="#2563eb" />
          </BarChart>
        </ChartCard>

        <ChartCard title={AZ.charts.priceVsMileage} subtitle="Nümunə 2000 elan" height={260} empty={!scatter?.length}>
          <ScatterChart margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" dataKey="odometer" name="Yürüş" tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <YAxis type="number" dataKey="price_azn" name="Qiymət" tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <ZAxis range={[20, 20]} />
            <Tooltip formatter={(v, n) => [n === "price_azn" ? fmtAzn(v as number) : `${(v as number).toLocaleString()} km`, n === "price_azn" ? "Qiymət" : "Yürüş"]} />
            <Scatter data={scatter ?? []} fill="#2563eb" opacity={0.5} />
          </ScatterChart>
        </ChartCard>
      </div>

      {/* Price trend */}
      <ChartCard title={AZ.charts.priceTrend} height={220} empty={!trend?.length}>
        <LineChart data={trend ?? []}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="period" tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
          <Tooltip formatter={fmtAzn} />
          <Line type="monotone" dataKey="avg" name="Ortalama" stroke="#2563eb" dot={false} strokeWidth={2} />
          <Line type="monotone" dataKey="median" name="Median" stroke="#16a34a" dot={false} strokeWidth={2} strokeDasharray="4 2" />
        </LineChart>
      </ChartCard>

      {/* By-city / seller-type / condition */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <ChartCard title={AZ.charts.priceByCity} height={240} empty={!byCity?.length}>
          <BarChart data={(byCity ?? []).slice(0, 12)} layout="vertical" margin={{ left: 60 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <YAxis dataKey="city" type="category" tick={{ fontSize: 9 }} width={55} />
            <Tooltip formatter={fmtAzn} />
            <Bar dataKey="median" name="Median" fill="#2563eb" />
          </BarChart>
        </ChartCard>

        <ChartCard title={AZ.charts.priceBySellerType} height={240} empty={!bySellerType?.length}>
          <BarChart data={bySellerType ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="seller_type" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <Tooltip formatter={fmtAzn} />
            <Bar dataKey="median" name="Median" fill="#8b5cf6" />
          </BarChart>
        </ChartCard>

        <ChartCard title={AZ.charts.priceByCondition} height={240} empty={!byCondition?.length}>
          <BarChart data={(byCondition ?? []).slice(0, 6)} layout="vertical" margin={{ left: 100 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <YAxis dataKey="condition" type="category" tick={{ fontSize: 8 }} width={95} />
            <Tooltip formatter={fmtAzn} />
            <Bar dataKey="median" name="Median" fill="#16a34a" />
          </BarChart>
        </ChartCard>
      </div>

      {/* Tabbed tables */}
      <div className="bg-white rounded-lg border">
        <div className="flex border-b overflow-x-auto">
          {tabItems.map((t) => (
            <button
              key={t.key}
              onClick={() => setTableTab(t.key)}
              className={`px-4 py-2.5 text-sm whitespace-nowrap border-b-2 transition-colors ${
                tableTab === t.key
                  ? "border-blue-600 text-blue-600 font-medium"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="p-4">
          {tableTab === "outliers" && outliers && (
            <p className="text-xs text-gray-500 mb-2">
              IQR sınırları: {fmtAzn(outliers.lo)} – {fmtAzn(outliers.hi)}
            </p>
          )}
          <DataTable
            columns={colsVehicle}
            data={activeTableData()}
            total={tableTab === "comparables" ? comparables?.total : undefined}
            pageIndex={tableTab === "comparables" ? comparablesPage : undefined}
            pageSize={50}
            onPageChange={tableTab === "comparables" ? setComparablesPage : undefined}
            manualPagination={tableTab === "comparables"}
            rowHref={(r) => r.url}
          />
        </div>
      </div>
    </div>
  );
}
