import { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, Tooltip, XAxis, YAxis,
} from "recharts";
import ChartCard from "../../components/analytics/ChartCard";
import DataTable from "../../components/analytics/DataTable";
import KpiCard from "../../components/analytics/KpiCard";
import { useAnalyticsFilters } from "../../hooks/useAnalyticsFilters";
import { useAnalyticsQuery } from "../../hooks/useAnalyticsQuery";
import { AZ } from "../../i18n/az";

interface CompetitorsKpis {
  total_active_sellers: number;
  total_business_sellers: number;
  avg_listings_per_seller: number | null;
  most_active_seller: string | null;
  most_active_seller_count: number;
}
interface SellerRow {
  seller_id: number;
  name: string;
  seller_type: string;
  city: string | null;
  active_count: number;
  total_listings: number;
  total_sold: number;
  avg_price: number | null;
  avg_dts: number | null;
}

const COLORS = ["#2563eb", "#16a34a", "#f59e0b", "#ef4444", "#8b5cf6"];
const sellerTypeLabels: Record<string, string> = { business: "Avtosalon", dealer: "Diler", private: "Şəxsi", unknown: "Digər" };
const fmtAzn = (v: number | null | undefined) => v != null ? `${Math.round(v).toLocaleString()} AZN` : "—";

const cols: ColumnDef<SellerRow, unknown>[] = [
  { accessorKey: "name", header: AZ.cols.sellerName },
  { accessorKey: "seller_type", header: AZ.cols.sellerType, cell: ({ getValue }) => sellerTypeLabels[getValue() as string] ?? getValue() as string },
  { accessorKey: "city", header: AZ.cols.city },
  { accessorKey: "active_count", header: "Aktiv elanlar" },
  { accessorKey: "total_listings", header: AZ.cols.totalListings },
  { accessorKey: "total_sold", header: AZ.kpis.totalSold },
  { accessorKey: "avg_price", header: AZ.cols.avgPrice, cell: ({ getValue }) => fmtAzn(getValue() as number) },
  { accessorKey: "avg_dts", header: AZ.cols.avgDts, cell: ({ getValue }) => getValue() != null ? `${getValue()} gün` : "—" },
];

export default function CompetitorsDashboard() {
  const { toParams } = useAnalyticsFilters();
  const p = toParams();
  const [page, setPage] = useState(0);

  const { data: kpis, loading: kLoading } = useAnalyticsQuery<CompetitorsKpis>("/analytics/competitors/kpis", p);
  const { data: topSellers } = useAnalyticsQuery<{ total: number; items: SellerRow[] }>(
    "/analytics/competitors/top-sellers",
    { ...p, limit: 20, offset: page * 20 },
  );
  const { data: byType } = useAnalyticsQuery<Array<{ seller_type: string; seller_count: number; listing_count: number; share_pct: number | null }>>("/analytics/competitors/by-type", p);
  const { data: priceStrategy } = useAnalyticsQuery<Array<{ seller_type: string; avg_price: number | null; median_price: number | null; count: number }>>("/analytics/competitors/price-strategy", p);

  const top20Chart = (topSellers?.items ?? []).slice(0, 20);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-800">{AZ.dashboards.competitors}</h1>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <KpiCard label={AZ.kpis.totalActiveSellers} value={kpis?.total_active_sellers} loading={kLoading} />
        <KpiCard label={AZ.kpis.totalBusinessSellers} value={kpis?.total_business_sellers} loading={kLoading} />
        <KpiCard label={AZ.kpis.avgListingsPerSeller} value={kpis?.avg_listings_per_seller} format="raw" sub={kpis?.avg_listings_per_seller != null ? `${kpis.avg_listings_per_seller} elan` : undefined} loading={kLoading} />
        <KpiCard label={AZ.kpis.mostActiveSeller} value={kpis?.most_active_seller} format="raw" tone="good" loading={kLoading} />
        <KpiCard label="Ən aktiv say" value={kpis?.most_active_seller_count} loading={kLoading} />
      </div>

      <ChartCard title={AZ.charts.topSellers} height={320} empty={!top20Chart.length}>
        <BarChart data={top20Chart} layout="vertical" margin={{ left: 120, right: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis type="number" tick={{ fontSize: 10 }} />
          <YAxis dataKey="name" type="category" tick={{ fontSize: 9 }} width={115} />
          <Tooltip />
          <Bar dataKey="active_count" name="Aktiv elanlar" fill="#2563eb" />
        </BarChart>
      </ChartCard>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="max-w-sm">
          <ChartCard title={AZ.charts.sellerTypeDistribution} height={240} empty={!byType?.length}>
            <PieChart>
              <Pie
                data={byType ?? []}
                dataKey="listing_count"
                nameKey="seller_type"
                cx="50%"
                cy="50%"
                outerRadius={80}
                label={({ seller_type, share_pct }) => `${sellerTypeLabels[seller_type] ?? seller_type}: ${share_pct}%`}
              >
                {(byType ?? []).map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip formatter={(v, name) => [v, sellerTypeLabels[name as string] ?? name]} />
            </PieChart>
          </ChartCard>
        </div>

        <ChartCard title={AZ.charts.priceBySellerTypeBar} height={240} empty={!priceStrategy?.length}>
          <BarChart data={priceStrategy ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="seller_type" tick={{ fontSize: 10 }} tickFormatter={(v) => sellerTypeLabels[v] ?? v} />
            <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <Tooltip
              formatter={(v) => fmtAzn(v as number)}
              labelFormatter={(v) => sellerTypeLabels[v as string] ?? v}
            />
            <Bar dataKey="median_price" name="Median" fill="#8b5cf6" />
          </BarChart>
        </ChartCard>
      </div>

      <div className="bg-white rounded-lg border">
        <div className="p-4 border-b">
          <h3 className="font-semibold text-gray-700 text-sm">{AZ.tables.topSellersTable}</h3>
        </div>
        <div className="p-4">
          <DataTable
            columns={cols}
            data={topSellers?.items ?? []}
            total={topSellers?.total}
            pageIndex={page}
            pageSize={20}
            onPageChange={setPage}
            manualPagination
          />
        </div>
      </div>
    </div>
  );
}
