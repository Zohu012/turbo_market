import { ColumnDef } from "@tanstack/react-table";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, Tooltip, XAxis, YAxis,
} from "recharts";
import ChartCard from "../../components/analytics/ChartCard";
import DataTable from "../../components/analytics/DataTable";
import KpiCard from "../../components/analytics/KpiCard";
import { useAnalyticsFilters } from "../../hooks/useAnalyticsFilters";
import { useAnalyticsQuery } from "../../hooks/useAnalyticsQuery";
import { AZ } from "../../i18n/az";

interface LiquidityKpis {
  avg_active_inventory: number;
  deactivated_30d: number;
  turnover_rate: number | null;
  days_of_supply: number | null;
  most_liquid_make: string | null;
  least_liquid_make: string | null;
}
interface MakeRow {
  make: string; active: number; deact_30d: number;
  turnover_rate: number | null; days_of_supply: number | null;
}
interface MakeModelRow extends MakeRow { model: string }

const pct = (v: number | null | undefined) => v != null ? `${(v * 100).toFixed(1)}%` : "—";

const tableCols: ColumnDef<MakeModelRow, unknown>[] = [
  { accessorKey: "make", header: AZ.cols.make },
  { accessorKey: "model", header: AZ.cols.model },
  { accessorKey: "active", header: AZ.cols.activeTrend },
  { accessorKey: "deact_30d", header: AZ.kpis.deactivated30d2 },
  { accessorKey: "turnover_rate", header: AZ.cols.turnoverRate, cell: ({ getValue }) => pct(getValue() as number) },
  { accessorKey: "days_of_supply", header: AZ.cols.daysOfSupply, cell: ({ getValue }) => getValue() != null ? `${getValue()} gün` : "—" },
];

export default function LiquidityDashboard() {
  const { toParams } = useAnalyticsFilters();
  const p = toParams();

  const { data: kpis, loading: kLoading } = useAnalyticsQuery<LiquidityKpis>("/analytics/liquidity/kpis", p);
  const { data: byMake } = useAnalyticsQuery<MakeRow[]>("/analytics/liquidity/by-make", p);
  const { data: byCity } = useAnalyticsQuery<Array<{ city: string; active: number; deact_30d: number; turnover_rate: number | null }>>("/analytics/liquidity/by-city", p);
  const { data: trend } = useAnalyticsQuery<Array<{ period: string; added: number; deactivated: number }>>("/analytics/liquidity/trend", p);
  const { data: table } = useAnalyticsQuery<MakeModelRow[]>("/analytics/liquidity/table", p);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-800">{AZ.dashboards.liquidity}</h1>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard label={AZ.kpis.avgActiveInventory} value={kpis?.avg_active_inventory} loading={kLoading} />
        <KpiCard label={AZ.kpis.deactivated30d} value={kpis?.deactivated_30d} tone="warn" loading={kLoading} />
        <KpiCard label={AZ.kpis.turnoverRate} value={kpis?.turnover_rate != null ? kpis.turnover_rate * 100 : null} format="raw" sub={kpis?.turnover_rate != null ? `${(kpis.turnover_rate * 100).toFixed(1)}%` : undefined} loading={kLoading} />
        <KpiCard label={AZ.kpis.daysOfSupply} value={kpis?.days_of_supply} format="days" loading={kLoading} />
        <KpiCard label={AZ.kpis.mostLiquidMake} value={kpis?.most_liquid_make} format="raw" tone="good" loading={kLoading} />
        <KpiCard label={AZ.kpis.leastLiquidMake} value={kpis?.least_liquid_make} format="raw" tone="bad" loading={kLoading} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title={AZ.charts.turnoverByMake} height={280} empty={!byMake?.length}>
          <BarChart data={byMake ?? []} layout="vertical" margin={{ left: 55, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
            <YAxis dataKey="make" type="category" tick={{ fontSize: 10 }} width={50} />
            <Tooltip formatter={(v) => [`${((v as number) * 100).toFixed(1)}%`, "Dövriyyə"]} />
            <Bar dataKey="turnover_rate" name="Dövriyyə" fill="#2563eb" />
          </BarChart>
        </ChartCard>

        <ChartCard title={AZ.charts.turnoverByCity} height={280} empty={!byCity?.length}>
          <BarChart data={byCity ?? []} layout="vertical" margin={{ left: 80, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
            <YAxis dataKey="city" type="category" tick={{ fontSize: 10 }} width={75} />
            <Tooltip formatter={(v) => [`${((v as number) * 100).toFixed(1)}%`, "Dövriyyə"]} />
            <Bar dataKey="turnover_rate" name="Dövriyyə" fill="#16a34a" />
          </BarChart>
        </ChartCard>
      </div>

      <ChartCard title={AZ.charts.inventoryVsDeact} height={220} empty={!trend?.length}>
        <LineChart data={trend ?? []}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="period" tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip />
          <Legend />
          <Line type="monotone" dataKey="added" name="Əlavə" stroke="#16a34a" dot={false} strokeWidth={2} />
          <Line type="monotone" dataKey="deactivated" name="Deaktiv" stroke="#ef4444" dot={false} strokeWidth={2} />
        </LineChart>
      </ChartCard>

      <div className="bg-white rounded-lg border">
        <div className="p-4 border-b">
          <h3 className="font-semibold text-gray-700 text-sm">{AZ.tables.liquidityByMakeModel}</h3>
        </div>
        <div className="p-4">
          <DataTable columns={tableCols} data={table ?? []} />
        </div>
      </div>
    </div>
  );
}
