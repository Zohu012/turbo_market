import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  Pie, PieChart, Tooltip, XAxis, YAxis,
} from "recharts";
import ChartCard from "../../components/analytics/ChartCard";
import KpiCard from "../../components/analytics/KpiCard";
import { useAnalyticsFilters } from "../../hooks/useAnalyticsFilters";
import { useAnalyticsQuery } from "../../hooks/useAnalyticsQuery";
import { AZ } from "../../i18n/az";

const COLORS = ["#2563eb", "#16a34a", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4"];

function fmtAzn(v: number | null) {
  return v != null ? `${Math.round(v).toLocaleString()} AZN` : "—";
}

export default function OverviewDashboard() {
  const { toParams } = useAnalyticsFilters();
  const p = toParams();

  const { data: kpis, loading: kLoading } = useAnalyticsQuery<Record<string, unknown>>(
    "/analytics/overview/kpis", p,
  );
  const { data: byDay, loading: dayLoading } = useAnalyticsQuery<Array<{ period: string; count: number }>>(
    "/analytics/overview/listings-by-day", { ...p, days: 60 },
  );
  const { data: flow, loading: flowLoading } = useAnalyticsQuery<Array<{ period: string; added: number; deactivated: number }>>(
    "/analytics/overview/active-vs-inactive-trend", { ...p, days: 60 },
  );
  const { data: priceTrend, loading: ptLoading } = useAnalyticsQuery<Array<{ period: string; avg_price: number | null; median_price: number | null }>>(
    "/analytics/overview/median-price-trend", { ...p, days: 90 },
  );
  const { data: dtsTrend, loading: dtsLoading } = useAnalyticsQuery<Array<{ period: string; median_dts: number | null }>>(
    "/analytics/overview/dts-trend", { ...p, days: 180 },
  );
  const { data: byCity, loading: cityLoading } = useAnalyticsQuery<Array<{ city: string; count: number }>>(
    "/analytics/overview/listings-by-city", p,
  );
  const { data: byMake, loading: makeLoading } = useAnalyticsQuery<Array<{ make: string; active_count: number; inactive_count: number }>>(
    "/analytics/overview/listings-by-make", p,
  );
  const { data: sellerSplit, loading: splitLoading } = useAnalyticsQuery<Array<{ seller_type: string; count: number }>>(
    "/analytics/overview/seller-type-split", p,
  );

  const sellerLabels: Record<string, string> = { business: "Avtosalon", dealer: "Diler", private: "Şəxsi", unknown: "Digər" };

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-800">{AZ.dashboards.overview}</h1>

      {/* KPI grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-3">
        <KpiCard label={AZ.kpis.activeListings} value={kpis?.active as number} loading={kLoading} />
        <KpiCard label={AZ.kpis.newToday} value={kpis?.new_today as number} tone="good" loading={kLoading} />
        <KpiCard label={AZ.kpis.new7d} value={kpis?.new_7d as number} tone="good" loading={kLoading} />
        <KpiCard label={AZ.kpis.new30d} value={kpis?.new_30d as number} loading={kLoading} />
        <KpiCard label={AZ.kpis.deactivated30d} value={kpis?.deactivated_30d as number} tone="warn" loading={kLoading} />
        <KpiCard label={AZ.kpis.medianPrice} value={kpis?.median_price as number} format="azn" loading={kLoading} />
        <KpiCard label={AZ.kpis.avgPrice} value={kpis?.avg_price as number} format="azn" loading={kLoading} />
        <KpiCard label={AZ.kpis.avgMileage} value={kpis?.avg_mileage as number} format="number" sub="km" loading={kLoading} />
        <KpiCard label={AZ.kpis.avgDts} value={kpis?.avg_dts as number} format="days" loading={kLoading} />
        <KpiCard label={AZ.kpis.medianDts} value={kpis?.median_dts as number} format="days" loading={kLoading} />
        <KpiCard
          label={AZ.kpis.dealerShare}
          value={kpis?.dealer_share != null ? (kpis.dealer_share as number) * 100 : null}
          format="raw"
          sub={kpis?.dealer_share != null ? `${((kpis.dealer_share as number) * 100).toFixed(1)}%` : undefined}
          loading={kLoading}
        />
        <KpiCard
          label={AZ.kpis.priceTrend30d}
          value={kpis?.price_trend_30d_pct as number}
          format="raw"
          tone={(kpis?.price_trend_30d_pct as number) > 0 ? "good" : (kpis?.price_trend_30d_pct as number) < 0 ? "bad" : "default"}
          sub={kpis?.price_trend_30d_pct != null ? `${kpis.price_trend_30d_pct}%` : undefined}
          loading={kLoading}
        />
      </div>

      {/* Segment highlights */}
      {!kLoading && (kpis?.fastest_segment || kpis?.slowest_segment) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {kpis?.fastest_segment && (
            <div className="bg-green-50 border border-green-200 rounded-lg p-3 text-sm">
              <span className="font-semibold text-green-700">⚡ Ən tez satan: </span>
              <span className="text-green-900">
                {(kpis.fastest_segment as { make: string; model: string; avg_dts: number }).make}{" "}
                {(kpis.fastest_segment as { make: string; model: string; avg_dts: number }).model}
                {" — "}
                {(kpis.fastest_segment as { make: string; model: string; avg_dts: number }).avg_dts} gün
              </span>
            </div>
          )}
          {kpis?.slowest_segment && (
            <div className="bg-orange-50 border border-orange-200 rounded-lg p-3 text-sm">
              <span className="font-semibold text-orange-700">🐢 Ən yavaş satan: </span>
              <span className="text-orange-900">
                {(kpis.slowest_segment as { make: string; model: string; avg_dts: number }).make}{" "}
                {(kpis.slowest_segment as { make: string; model: string; avg_dts: number }).model}
                {" — "}
                {(kpis.slowest_segment as { make: string; model: string; avg_dts: number }).avg_dts} gün
              </span>
            </div>
          )}
        </div>
      )}

      {/* Charts row 1 */}
      <ChartCard title={AZ.charts.listingsByDay} height={220} loading={dayLoading} empty={!byDay?.length}>
        <LineChart data={byDay ?? []}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="period" tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip />
          <Line type="monotone" dataKey="count" name="Elanlar" stroke="#2563eb" dot={false} strokeWidth={2} />
        </LineChart>
      </ChartCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard
          title={AZ.charts.activeVsInactive}
          subtitle="Günlük əlavələr və deaktivlər"
          height={220}
          loading={flowLoading}
          empty={!flow?.length}
        >
          <LineChart data={flow ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="period" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip />
            <Legend />
            <Line type="monotone" dataKey="added" name="Əlavə" stroke="#16a34a" dot={false} strokeWidth={2} />
            <Line type="monotone" dataKey="deactivated" name="Deaktiv" stroke="#ef4444" dot={false} strokeWidth={2} />
          </LineChart>
        </ChartCard>

        <ChartCard title={AZ.charts.medianPriceTrend} height={220} loading={ptLoading} empty={!priceTrend?.length}>
          <LineChart data={priceTrend ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="period" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <Tooltip formatter={fmtAzn} />
            <Legend />
            <Line type="monotone" dataKey="avg_price" name="Ortalama" stroke="#2563eb" dot={false} strokeWidth={2} />
            <Line type="monotone" dataKey="median_price" name="Median" stroke="#16a34a" dot={false} strokeWidth={2} strokeDasharray="4 2" />
          </LineChart>
        </ChartCard>
      </div>

      <ChartCard title={AZ.charts.dtsTrend} subtitle="Median satış müddəti (həftəlik)" height={200} loading={dtsLoading} empty={!dtsTrend?.length}>
        <LineChart data={dtsTrend ?? []}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="period" tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip formatter={(v: number) => `${v} gün`} />
          <Line type="monotone" dataKey="median_dts" name="Median DTS" stroke="#8b5cf6" dot={false} strokeWidth={2} />
        </LineChart>
      </ChartCard>

      {/* Charts row 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title={AZ.charts.listingsByCity} height={280} loading={cityLoading} empty={!byCity?.length}>
          <BarChart data={(byCity ?? []).slice(0, 15)} layout="vertical" margin={{ left: 70, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} />
            <YAxis dataKey="city" type="category" tick={{ fontSize: 10 }} width={65} />
            <Tooltip />
            <Bar dataKey="count" name="Elanlar" fill="#2563eb" />
          </BarChart>
        </ChartCard>

        <ChartCard title={AZ.charts.listingsByMake} height={280} loading={makeLoading} empty={!byMake?.length}>
          <BarChart data={byMake ?? []} layout="vertical" margin={{ left: 60, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} />
            <YAxis dataKey="make" type="category" tick={{ fontSize: 10 }} width={55} />
            <Tooltip />
            <Legend />
            <Bar dataKey="active_count" name="Aktiv" fill="#2563eb" stackId="a" />
            <Bar dataKey="inactive_count" name="Deaktiv" fill="#d1d5db" stackId="a" />
          </BarChart>
        </ChartCard>
      </div>

      <div className="max-w-sm">
        <ChartCard title={AZ.charts.sellerTypeSplit} height={220} loading={splitLoading} empty={!sellerSplit?.length}>
          <PieChart>
            <Pie
              data={sellerSplit ?? []}
              dataKey="count"
              nameKey="seller_type"
              cx="50%"
              cy="50%"
              outerRadius={80}
              label={({ seller_type, count }) => `${sellerLabels[seller_type] ?? seller_type}: ${count}`}
            >
              {(sellerSplit ?? []).map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip formatter={(v, name) => [v, sellerLabels[name as string] ?? name]} />
          </PieChart>
        </ChartCard>
      </div>
    </div>
  );
}
