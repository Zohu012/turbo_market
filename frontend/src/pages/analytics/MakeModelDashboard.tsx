import { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Line, LineChart,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import ChartCard from "../../components/analytics/ChartCard";
import DataTable from "../../components/analytics/DataTable";
import KpiCard from "../../components/analytics/KpiCard";
import { useAnalyticsFilters } from "../../hooks/useAnalyticsFilters";
import { useAnalyticsQuery } from "../../hooks/useAnalyticsQuery";
import { AZ } from "../../i18n/az";

interface MmKpis {
  active_count: number; median_price: number | null; p10: number | null; p90: number | null;
  avg_price: number | null; avg_mileage: number | null; avg_dts: number | null; median_dts: number | null;
  dealer_share: number | null; private_share: number | null;
  top_cities: Array<{ city: string; count: number }>;
  liquidity_score: number | null; deactivated_30d: number; price_trend_30d_pct: number | null;
}
interface VehicleRow {
  id: number; turbo_id: number; make: string; model: string; year: number | null;
  price_azn: number | null; odometer: number | null; city: string | null;
  condition: string | null; transmission: string | null; url: string;
  date_deactivated?: string | null; days_to_sell?: number | null;
}
interface SimilarRow { make: string; model: string; active_count: number; median_price: number | null }
interface FlowRow { period: string; added: number; deactivated: number }
interface BandRow { city?: string; condition?: string; transmission?: string; avg: number | null; median: number | null; count: number }
interface DtsBucket { bucket: number; lo: number; hi: number; count: number }
interface ScatterPoint { id: number; odometer: number; price_azn: number; year: number | null; condition: string | null }

const fmtAzn = (v: number | null | undefined) => (v != null ? `${Math.round(v).toLocaleString()} AZN` : "—");

const colsVehicle: ColumnDef<VehicleRow, unknown>[] = [
  { accessorKey: "make", header: AZ.cols.make },
  { accessorKey: "model", header: AZ.cols.model },
  { accessorKey: "year", header: AZ.cols.year },
  { accessorKey: "price_azn", header: AZ.cols.price, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "odometer", header: AZ.cols.odometer, cell: ({ getValue }) => getValue() != null ? `${(getValue() as number).toLocaleString()} km` : "—" },
  { accessorKey: "city", header: AZ.cols.city },
  { accessorKey: "condition", header: AZ.cols.condition },
  { accessorKey: "days_to_sell", header: AZ.cols.daysToSell, cell: ({ getValue }) => getValue() != null ? `${getValue()} gün` : "—" },
];

const colsSimilar: ColumnDef<SimilarRow, unknown>[] = [
  { accessorKey: "make", header: AZ.cols.make },
  { accessorKey: "model", header: AZ.cols.model },
  { accessorKey: "active_count", header: AZ.cols.count },
  { accessorKey: "median_price", header: AZ.cols.medianPrice, cell: ({ getValue }) => fmtAzn(getValue() as number) },
];

type TableTab = "comparables" | "recent" | "cheapest" | "overpriced" | "similar";

export default function MakeModelDashboard() {
  const { filters, setFilters, toParams } = useAnalyticsFilters();
  const p = toParams();
  const [tableTab, setTableTab] = useState<TableTab>("comparables");
  const [page, setPage] = useState(0);

  // Make/model picker if no make selected
  const [localMake, setLocalMake] = useState("");
  const [localModel, setLocalModel] = useState("");

  const hasMake = !!filters.make;

  const { data: kpis, loading: kLoading } = useAnalyticsQuery<MmKpis>(
    "/analytics/makemodel/kpis", p, { skip: !hasMake }
  );
  const { data: scatter } = useAnalyticsQuery<ScatterPoint[]>(
    "/analytics/makemodel/price-vs-mileage", p, { skip: !hasMake }
  );
  const { data: byCity } = useAnalyticsQuery<BandRow[]>(
    "/analytics/makemodel/price-by-city", p, { skip: !hasMake }
  );
  const { data: byCondition } = useAnalyticsQuery<BandRow[]>(
    "/analytics/makemodel/price-by-condition", p, { skip: !hasMake }
  );
  const { data: byTransmission } = useAnalyticsQuery<BandRow[]>(
    "/analytics/makemodel/price-by-transmission", p, { skip: !hasMake }
  );
  const { data: flow } = useAnalyticsQuery<FlowRow[]>(
    "/analytics/makemodel/active-vs-deactivated-trend", p, { skip: !hasMake }
  );
  const { data: dtsDist } = useAnalyticsQuery<DtsBucket[]>(
    "/analytics/makemodel/dts-distribution", p, { skip: !hasMake }
  );

  const { data: comparables } = useAnalyticsQuery<{ total: number; items: VehicleRow[] }>(
    "/analytics/makemodel/comparables", { ...p, offset: page * 50, limit: 50 },
    { skip: !hasMake || tableTab !== "comparables" }
  );
  const { data: recent } = useAnalyticsQuery<VehicleRow[]>(
    "/analytics/makemodel/recent-deactivated", p, { skip: !hasMake || tableTab !== "recent" }
  );
  const { data: cheapest } = useAnalyticsQuery<VehicleRow[]>(
    "/analytics/makemodel/cheapest", p, { skip: !hasMake || tableTab !== "cheapest" }
  );
  const { data: overpriced } = useAnalyticsQuery<{ p75: number | null; items: VehicleRow[] }>(
    "/analytics/makemodel/overpriced", p, { skip: !hasMake || tableTab !== "overpriced" }
  );
  const { data: similar } = useAnalyticsQuery<SimilarRow[]>(
    "/analytics/makemodel/similar-models", p, { skip: !hasMake || tableTab !== "similar" }
  );

  if (!hasMake) {
    return (
      <div className="space-y-6">
        <h1 className="text-xl font-bold text-gray-800">{AZ.dashboards.makemodel}</h1>
        <div className="bg-white rounded-lg border p-8 text-center max-w-sm mx-auto">
          <p className="text-gray-500 mb-4 text-sm">Marka seçin:</p>
          <input
            type="text"
            placeholder="Marka (məs. Toyota)"
            value={localMake}
            onChange={(e) => setLocalMake(e.target.value)}
            className="border rounded px-3 py-2 text-sm w-full mb-2"
          />
          <input
            type="text"
            placeholder="Model (isteğe bağlı)"
            value={localModel}
            onChange={(e) => setLocalModel(e.target.value)}
            className="border rounded px-3 py-2 text-sm w-full mb-3"
          />
          <button
            onClick={() => {
              if (localMake.trim()) {
                setFilters({ make: localMake.trim(), model: localModel.trim() || undefined }, true);
              }
            }}
            className="bg-blue-600 text-white rounded px-4 py-2 text-sm hover:bg-blue-700 w-full"
          >
            Axtar
          </button>
        </div>
      </div>
    );
  }

  const tabItems: Array<{ key: TableTab; label: string }> = [
    { key: "comparables", label: AZ.tables.comparableListings },
    { key: "recent", label: AZ.tables.recentDeactivated },
    { key: "cheapest", label: AZ.tables.cheapest },
    { key: "overpriced", label: AZ.tables.overpriced },
    { key: "similar", label: AZ.tables.similarModels },
  ];

  const activeData = (): VehicleRow[] | SimilarRow[] => {
    if (tableTab === "comparables") return comparables?.items ?? [];
    if (tableTab === "recent") return recent ?? [];
    if (tableTab === "cheapest") return cheapest ?? [];
    if (tableTab === "overpriced") return overpriced?.items ?? [];
    if (tableTab === "similar") return similar ?? [];
    return [];
  };

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-800">
        {AZ.dashboards.makemodel}: {filters.make}
        {filters.model ? ` ${filters.model}` : ""}
      </h1>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">
        <KpiCard label={AZ.kpis.activeListings} value={kpis?.active_count} loading={kLoading} />
        <KpiCard label={AZ.kpis.medianPrice} value={kpis?.median_price} format="azn" loading={kLoading} />
        <KpiCard label={AZ.kpis.p10} value={kpis?.p10} format="azn" loading={kLoading} />
        <KpiCard label={AZ.kpis.p90} value={kpis?.p90} format="azn" loading={kLoading} />
        <KpiCard label={AZ.kpis.avgMileage} value={kpis?.avg_mileage} format="number" sub="km" loading={kLoading} />
        <KpiCard label={AZ.kpis.avgDts} value={kpis?.avg_dts} format="days" loading={kLoading} />
        <KpiCard label={AZ.kpis.liquidity} value={kpis?.liquidity_score} format="raw"
          sub={kpis?.liquidity_score != null ? `${kpis.liquidity_score.toFixed(2)}×` : undefined}
          tone={kpis?.liquidity_score != null && kpis.liquidity_score > 1 ? "good" : "warn"}
          loading={kLoading}
        />
        <KpiCard label={AZ.kpis.deactivated30d2} value={kpis?.deactivated_30d} loading={kLoading} />
        <KpiCard
          label={AZ.kpis.priceTrend30d}
          value={kpis?.price_trend_30d_pct}
          format="raw"
          sub={kpis?.price_trend_30d_pct != null ? `${kpis.price_trend_30d_pct}%` : undefined}
          tone={(kpis?.price_trend_30d_pct ?? 0) > 0 ? "good" : "bad"}
          loading={kLoading}
        />
        <KpiCard label={AZ.kpis.dealerShare} value={kpis?.dealer_share != null ? kpis.dealer_share * 100 : null}
          format="raw" sub={kpis?.dealer_share != null ? `${(kpis.dealer_share * 100).toFixed(1)}%` : undefined}
          loading={kLoading}
        />
      </div>

      {/* Top cities chips */}
      {kpis?.top_cities?.length && (
        <div className="flex flex-wrap gap-2">
          {kpis.top_cities.map((c) => (
            <span key={c.city} className="bg-blue-50 text-blue-700 text-xs rounded-full px-3 py-1">
              {c.city}: {c.count}
            </span>
          ))}
        </div>
      )}

      {/* Charts row 1: scatter + by-city */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title={AZ.charts.priceVsMileage} height={260} empty={!scatter?.length}>
          <ScatterChart margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" dataKey="odometer" tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <YAxis type="number" dataKey="price_azn" tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <ZAxis range={[20, 20]} />
            <Tooltip formatter={(v, n) => [n === "price_azn" ? fmtAzn(v as number) : `${(v as number).toLocaleString()} km`, n === "price_azn" ? "Qiymət" : "Yürüş"]} />
            <Scatter data={scatter ?? []} fill="#2563eb" opacity={0.5} />
          </ScatterChart>
        </ChartCard>

        <ChartCard title={AZ.charts.priceByCity} height={260} empty={!byCity?.length}>
          <BarChart data={(byCity ?? []).slice(0, 12)} layout="vertical" margin={{ left: 60 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <YAxis dataKey="city" type="category" tick={{ fontSize: 9 }} width={55} />
            <Tooltip formatter={(v) => fmtAzn(v as number)} />
            <Bar dataKey="median" name="Median" fill="#2563eb" />
          </BarChart>
        </ChartCard>
      </div>

      {/* Charts row 2: condition + transmission */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ChartCard title={AZ.charts.priceByCondition} height={220} empty={!byCondition?.length}>
          <BarChart data={(byCondition ?? []).slice(0, 6)} layout="vertical" margin={{ left: 100 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <YAxis dataKey="condition" type="category" tick={{ fontSize: 8 }} width={95} />
            <Tooltip formatter={(v) => fmtAzn(v as number)} />
            <Bar dataKey="median" name="Median" fill="#16a34a" />
          </BarChart>
        </ChartCard>

        <ChartCard title="Sürətlər qutusu üzrə qiymət" height={220} empty={!byTransmission?.length}>
          <BarChart data={byTransmission ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="transmission" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <Tooltip formatter={(v) => fmtAzn(v as number)} />
            <Bar dataKey="median" name="Median" fill="#8b5cf6" />
          </BarChart>
        </ChartCard>
      </div>

      {/* Flow trend + DTS distribution */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title={AZ.charts.activeVsDeactivatedTrend} subtitle="Həftəlik axın" height={220} empty={!flow?.length}>
          <LineChart data={flow ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="period" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip />
            <Line type="monotone" dataKey="added" name="Əlavə" stroke="#16a34a" dot={false} strokeWidth={2} />
            <Line type="monotone" dataKey="deactivated" name="Deaktiv" stroke="#ef4444" dot={false} strokeWidth={2} />
          </LineChart>
        </ChartCard>

        <ChartCard title={AZ.charts.dtsDistribution} height={220} empty={!dtsDist?.length}>
          <BarChart data={dtsDist ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="lo" tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}g`} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip formatter={(v) => [v, "Elanlar"]} />
            <Bar dataKey="count" name="Say" fill="#8b5cf6" />
          </BarChart>
        </ChartCard>
      </div>

      {/* Tabbed tables */}
      <div className="bg-white rounded-lg border">
        <div className="flex border-b overflow-x-auto">
          {tabItems.map((t) => (
            <button
              key={t.key}
              onClick={() => { setTableTab(t.key); setPage(0); }}
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
          {tableTab === "overpriced" && overpriced?.p75 != null && (
            <p className="text-xs text-gray-500 mb-2">P75 = {fmtAzn(overpriced.p75)}</p>
          )}
          {tableTab === "similar" ? (
            <DataTable columns={colsSimilar} data={(activeData() as SimilarRow[])} />
          ) : (
            <DataTable
              columns={colsVehicle}
              data={(activeData() as VehicleRow[])}
              total={tableTab === "comparables" ? comparables?.total : undefined}
              pageIndex={tableTab === "comparables" ? page : undefined}
              pageSize={50}
              onPageChange={tableTab === "comparables" ? setPage : undefined}
              manualPagination={tableTab === "comparables"}
              rowHref={(r) => (r as VehicleRow).url}
            />
          )}
        </div>
      </div>
    </div>
  );
}
