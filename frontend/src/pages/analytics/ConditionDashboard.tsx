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

interface ConditionKpis {
  distinct_conditions: number;
  most_common_condition: string | null;
  most_common_count: number;
  total_with_condition: number;
}
interface ConditionRow {
  condition: string;
  count: number;
  share_pct: number | null;
  avg_price: number | null;
  median_price: number | null;
  avg_dts: number | null;
  median_dts: number | null;
}

const fmtAzn = (v: number | null | undefined) => v != null ? `${Math.round(v).toLocaleString()} AZN` : "—";

const cols: ColumnDef<ConditionRow, unknown>[] = [
  { accessorKey: "condition", header: AZ.cols.condition },
  { accessorKey: "count", header: AZ.cols.count },
  { accessorKey: "share_pct", header: AZ.cols.sharePct, cell: ({ getValue }) => getValue() != null ? `${getValue()}%` : "—" },
  { accessorKey: "median_price", header: AZ.cols.medianPrice, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "avg_price", header: AZ.cols.avgPrice, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "avg_dts", header: AZ.cols.avgDts, cell: ({ getValue }) => getValue() != null ? `${getValue()} gün` : "—" },
  { accessorKey: "median_dts", header: AZ.cols.medianDts, cell: ({ getValue }) => getValue() != null ? `${getValue()} gün` : "—" },
];

export default function ConditionDashboard() {
  const { toParams } = useAnalyticsFilters();
  const p = toParams();

  const { data: kpis, loading: kLoading } = useAnalyticsQuery<ConditionKpis>("/analytics/condition/kpis", p);
  const { data: overview } = useAnalyticsQuery<ConditionRow[]>("/analytics/condition/overview", p);
  const { data: priceDist } = useAnalyticsQuery<Array<{ condition: string; p25: number | null; median: number | null; p75: number | null; count: number }>>("/analytics/condition/price-dist", p);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-800">{AZ.dashboards.condition}</h1>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label={AZ.kpis.distinctConditions} value={kpis?.distinct_conditions} loading={kLoading} />
        <KpiCard label={AZ.kpis.mostCommonCondition} value={kpis?.most_common_condition} format="raw" tone="good" loading={kLoading} />
        <KpiCard label="Ən çox rastlanan say" value={kpis?.most_common_count} loading={kLoading} />
        <KpiCard label="Vəziyyəti olan elanlar" value={kpis?.total_with_condition} loading={kLoading} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <ChartCard title={AZ.charts.conditionCount} height={260} empty={!overview?.length}>
          <BarChart data={(overview ?? []).slice(0, 6)} layout="vertical" margin={{ left: 120, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} />
            <YAxis dataKey="condition" type="category" tick={{ fontSize: 8 }} width={115} />
            <Tooltip />
            <Bar dataKey="count" name="Say" fill="#2563eb" />
          </BarChart>
        </ChartCard>

        <ChartCard title={AZ.charts.conditionPrice} height={260} empty={!priceDist?.length}>
          <BarChart data={(priceDist ?? []).slice(0, 6)} layout="vertical" margin={{ left: 120, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <YAxis dataKey="condition" type="category" tick={{ fontSize: 8 }} width={115} />
            <Tooltip formatter={(v) => fmtAzn(v as number)} />
            <Bar dataKey="median" name="Median" fill="#16a34a" />
          </BarChart>
        </ChartCard>

        <ChartCard title={AZ.charts.conditionDts} height={260} empty={!overview?.length}>
          <BarChart data={(overview ?? []).filter((r) => r.avg_dts != null).slice(0, 6)} layout="vertical" margin={{ left: 120, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} />
            <YAxis dataKey="condition" type="category" tick={{ fontSize: 8 }} width={115} />
            <Tooltip formatter={(v) => [`${v} gün`, "Ort. satış"]} />
            <Bar dataKey="avg_dts" name="Ort. satış" fill="#8b5cf6" />
          </BarChart>
        </ChartCard>
      </div>

      <div className="bg-white rounded-lg border">
        <div className="p-4 border-b">
          <h3 className="font-semibold text-gray-700 text-sm">{AZ.tables.conditionComparison}</h3>
        </div>
        <div className="p-4">
          <DataTable columns={cols} data={overview ?? []} />
        </div>
      </div>
    </div>
  );
}
