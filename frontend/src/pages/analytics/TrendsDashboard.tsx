import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, Tooltip, XAxis, YAxis,
} from "recharts";
import ChartCard from "../../components/analytics/ChartCard";
import KpiCard from "../../components/analytics/KpiCard";
import { useAnalyticsFilters } from "../../hooks/useAnalyticsFilters";
import { useAnalyticsQuery } from "../../hooks/useAnalyticsQuery";
import { AZ } from "../../i18n/az";

interface TrendsKpis {
  oldest_data_point: string | null;
  price_change_12m_pct: number | null;
  price_change_6m_pct: number | null;
  inventory_change_12m_pct: number | null;
  dts_change_6m_pct: number | null;
}

const fmtAzn = (v: number | null | undefined) => v != null ? `${Math.round(v).toLocaleString()} AZN` : "—";
const fmtPct = (v: number | null | undefined) => v != null ? `${v > 0 ? "+" : ""}${v}%` : "—";
const tone = (v: number | null | undefined) =>
  v == null ? "default" : v > 0 ? "good" : v < 0 ? "bad" : "default";

export default function TrendsDashboard() {
  const { toParams } = useAnalyticsFilters();
  const p = toParams();

  const { data: kpis, loading: kLoading } = useAnalyticsQuery<TrendsKpis>("/analytics/trends/kpis", p);
  const { data: priceData } = useAnalyticsQuery<Array<{ period: string; avg: number | null; median: number | null; count: number }>>("/analytics/trends/price", { ...p, months: 24 });
  const { data: invData } = useAnalyticsQuery<Array<{ period: string; added: number; deactivated: number }>>("/analytics/trends/inventory", { ...p, months: 24 });
  const { data: dtsData } = useAnalyticsQuery<Array<{ period: string; avg_dts: number | null; median_dts: number | null; count: number }>>("/analytics/trends/dts", { ...p, months: 12 });

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-800">{AZ.dashboards.trends}</h1>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <KpiCard label={AZ.kpis.oldestDataPoint} value={kpis?.oldest_data_point ?? null} format="raw" loading={kLoading} />
        <KpiCard label={AZ.kpis.priceChange12m} value={kpis?.price_change_12m_pct} format="raw" sub={fmtPct(kpis?.price_change_12m_pct)} tone={tone(kpis?.price_change_12m_pct)} loading={kLoading} />
        <KpiCard label={AZ.kpis.priceChange6m} value={kpis?.price_change_6m_pct} format="raw" sub={fmtPct(kpis?.price_change_6m_pct)} tone={tone(kpis?.price_change_6m_pct)} loading={kLoading} />
        <KpiCard label={AZ.kpis.inventoryChange12m} value={kpis?.inventory_change_12m_pct} format="raw" sub={fmtPct(kpis?.inventory_change_12m_pct)} tone={tone(kpis?.inventory_change_12m_pct)} loading={kLoading} />
        <KpiCard label={AZ.kpis.dtsChange6m} value={kpis?.dts_change_6m_pct} format="raw" sub={fmtPct(kpis?.dts_change_6m_pct)} tone={tone(kpis?.dts_change_6m_pct)} loading={kLoading} />
      </div>

      <ChartCard title={AZ.charts.monthlyPrice} height={240} empty={!priceData?.length}>
        <LineChart data={priceData ?? []}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="period" tick={{ fontSize: 9 }} />
          <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
          <Tooltip formatter={(v) => fmtAzn(v as number)} />
          <Legend />
          <Line type="monotone" dataKey="avg" name="Ortalama" stroke="#2563eb" dot={false} strokeWidth={2} />
          <Line type="monotone" dataKey="median" name="Median" stroke="#16a34a" dot={false} strokeWidth={2} strokeDasharray="4 2" />
        </LineChart>
      </ChartCard>

      <ChartCard title={AZ.charts.monthlyInventory} height={240} empty={!invData?.length}>
        <BarChart data={invData ?? []}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="period" tick={{ fontSize: 9 }} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip />
          <Legend />
          <Bar dataKey="added" name="Əlavə" fill="#16a34a" />
          <Bar dataKey="deactivated" name="Deaktiv" fill="#ef4444" />
        </BarChart>
      </ChartCard>

      <ChartCard title={AZ.charts.monthlyDts} height={220} empty={!dtsData?.length}>
        <LineChart data={dtsData ?? []}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="period" tick={{ fontSize: 9 }} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip formatter={(v) => [`${v} gün`, ""]} />
          <Legend />
          <Line type="monotone" dataKey="avg_dts" name="Ortalama DTS" stroke="#8b5cf6" dot={false} strokeWidth={2} />
          <Line type="monotone" dataKey="median_dts" name="Median DTS" stroke="#f59e0b" dot={false} strokeWidth={2} strokeDasharray="4 2" />
        </LineChart>
      </ChartCard>
    </div>
  );
}
