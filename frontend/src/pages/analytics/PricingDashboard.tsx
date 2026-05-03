import { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, ReferenceLine, Scatter, ScatterChart,
  Tooltip, XAxis, YAxis, ZAxis,
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
interface VehicleRow {
  id: number; turbo_id: number; make: string; model: string; year: number | null;
  price_azn: number | null; odometer: number | null; city: string | null; url: string;
}
interface ScatterPoint { id: number; odometer: number; price_azn: number; year: number | null; make: string; model: string }

const confidenceLabel: Record<string, string> = { low: "Aşağı", medium: "Orta", high: "Yüksək" };
const fmtAzn = (v: number | null | undefined) => v != null ? `${Math.round(v).toLocaleString()} AZN` : "—";

const cols: ColumnDef<VehicleRow, unknown>[] = [
  { accessorKey: "make", header: AZ.cols.make },
  { accessorKey: "model", header: AZ.cols.model },
  { accessorKey: "year", header: AZ.cols.year },
  { accessorKey: "price_azn", header: AZ.cols.price, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "odometer", header: AZ.cols.odometer, cell: ({ getValue }) => getValue() != null ? `${(getValue() as number).toLocaleString()} km` : "—" },
  { accessorKey: "city", header: AZ.cols.city },
];

export default function PricingDashboard() {
  const { toParams } = useAnalyticsFilters();
  const p = toParams();
  const [page, setPage] = useState(0);

  const { data: kpis, loading: kLoading } = useAnalyticsQuery<PriceKpis>("/analytics/price/kpis", p);
  const { data: hist } = useAnalyticsQuery<{ buckets: HistBucket[] }>("/analytics/price/distribution", p);
  const { data: scatter } = useAnalyticsQuery<ScatterPoint[]>("/analytics/price/vs-mileage", p);
  const { data: comparables } = useAnalyticsQuery<{ total: number; items: VehicleRow[] }>(
    "/analytics/price/comparables",
    { ...p, offset: page * 50, limit: 50 },
  );

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-800">{AZ.dashboards.pricing}</h1>
      <p className="text-sm text-gray-500">
        Filtrləri tənzimləyərək (marka, model, il, vəziyyət, yürüş) sizin avtomobilinizə uyğun qiymət aralığını görün.
      </p>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard label={AZ.kpis.recommendedPrice} value={kpis?.median} format="azn" tone="good" loading={kLoading} />
        <KpiCard label={AZ.kpis.aggressivePrice} value={kpis?.p25} format="azn" loading={kLoading} />
        <KpiCard label={AZ.kpis.premiumPrice} value={kpis?.p75} format="azn" loading={kLoading} />
        <KpiCard label={AZ.kpis.p10} value={kpis?.p10} format="azn" loading={kLoading} />
        <KpiCard label={AZ.kpis.comparableCount} value={kpis?.count} loading={kLoading} />
        <KpiCard
          label={AZ.kpis.confidence}
          value={kpis?.confidence != null ? confidenceLabel[kpis.confidence] ?? kpis.confidence : null}
          format="raw"
          tone={kpis?.confidence === "high" ? "good" : kpis?.confidence === "low" ? "bad" : "warn"}
          loading={kLoading}
        />
      </div>

      {!kLoading && !!kpis?.p25 && !!kpis?.p75 && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800">
          Ədalətli qiymət aralığı: <strong>{fmtAzn(kpis.p25)}</strong> — <strong>{fmtAzn(kpis.p75)}</strong>
          {" "} (P25 – P75). Median tövsiyə: <strong>{fmtAzn(kpis.median)}</strong>
        </div>
      )}

      <ChartCard title={AZ.charts.priceDistribution} height={240} empty={!hist?.buckets?.length}>
        <BarChart data={hist?.buckets ?? []}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="lo" tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip
            formatter={(v) => [v, "Elanlar"]}
            labelFormatter={(_, pl) => pl[0] ? `${Math.round(pl[0].payload.lo / 1000)}k–${Math.round(pl[0].payload.hi / 1000)}k AZN` : ""}
          />
          {!!kpis?.median && <ReferenceLine x={kpis.median} stroke="#16a34a" strokeDasharray="4 2" label={{ value: "Tövsiyə", fill: "#16a34a", fontSize: 10 }} />}
          <Bar dataKey="count" name="Say" fill="#2563eb" />
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

      <div className="bg-white rounded-lg border">
        <div className="p-4 border-b">
          <h3 className="font-semibold text-gray-700 text-sm">{AZ.tables.comparableListings}</h3>
        </div>
        <div className="p-4">
          <DataTable
            columns={cols}
            data={comparables?.items ?? []}
            total={comparables?.total}
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
