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

interface FeaturesKpis {
  total_features_tracked: number;
  max_premium_feature: string | null;
  max_premium_azn: number | null;
  pct_vehicles_with_feature: number | null;
  overall_avg_price: number | null;
}
interface FeatureRow {
  feature_name: string;
  count_with: number;
  avg_with: number | null;
  avg_without: number | null;
  premium_azn: number | null;
  premium_pct: number | null;
}

const fmtAzn = (v: number | null | undefined) => v != null ? `${Math.round(v).toLocaleString()} AZN` : "—";

const cols: ColumnDef<FeatureRow, unknown>[] = [
  { accessorKey: "feature_name", header: AZ.cols.featureName },
  { accessorKey: "count_with", header: AZ.cols.countWith },
  { accessorKey: "avg_with", header: AZ.cols.avgWith, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "avg_without", header: AZ.cols.avgWithout, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "premium_azn", header: AZ.cols.premiumAzn, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "premium_pct", header: AZ.cols.premiumPct, cell: ({ getValue }) => getValue() != null ? `${getValue()}%` : "—" },
];

export default function FeaturesDashboard() {
  const { toParams } = useAnalyticsFilters();
  const p = toParams();

  const { data: kpis, loading: kLoading } = useAnalyticsQuery<FeaturesKpis>("/analytics/features/kpis", p);
  const { data: impact } = useAnalyticsQuery<FeatureRow[]>("/analytics/features/impact", p);

  const top20Premium = (impact ?? []).slice(0, 20);
  const top20Count = [...(impact ?? [])].sort((a, b) => b.count_with - a.count_with).slice(0, 20);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-800">{AZ.dashboards.features}</h1>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label={AZ.kpis.totalFeaturesTracked} value={kpis?.total_features_tracked} loading={kLoading} />
        <KpiCard label={AZ.kpis.maxPremiumFeature} value={kpis?.max_premium_feature} format="raw" tone="good" loading={kLoading} />
        <KpiCard label={AZ.kpis.maxPremiumAzn} value={kpis?.max_premium_azn} format="azn" tone="good" loading={kLoading} />
        <KpiCard
          label={AZ.kpis.pctWithFeature}
          value={kpis?.pct_vehicles_with_feature != null ? kpis.pct_vehicles_with_feature * 100 : null}
          format="raw"
          sub={kpis?.pct_vehicles_with_feature != null ? `${(kpis.pct_vehicles_with_feature * 100).toFixed(1)}%` : undefined}
          loading={kLoading}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title={AZ.charts.featuresByPremium} height={380} empty={!top20Premium.length}>
          <BarChart data={top20Premium} layout="vertical" margin={{ left: 140, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <YAxis dataKey="feature_name" type="category" tick={{ fontSize: 9 }} width={135} />
            <Tooltip formatter={(v) => fmtAzn(v as number)} />
            <Bar dataKey="premium_azn" name="Premium" fill="#16a34a" />
          </BarChart>
        </ChartCard>

        <ChartCard title={AZ.charts.featuresByCount} height={380} empty={!top20Count.length}>
          <BarChart data={top20Count} layout="vertical" margin={{ left: 140, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} />
            <YAxis dataKey="feature_name" type="category" tick={{ fontSize: 9 }} width={135} />
            <Tooltip />
            <Bar dataKey="count_with" name="Say" fill="#2563eb" />
          </BarChart>
        </ChartCard>
      </div>

      <div className="bg-white rounded-lg border">
        <div className="p-4 border-b">
          <h3 className="font-semibold text-gray-700 text-sm">{AZ.tables.featureImpact}</h3>
        </div>
        <div className="p-4">
          <DataTable columns={cols} data={impact ?? []} />
        </div>
      </div>
    </div>
  );
}
