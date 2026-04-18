import { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar, Legend
} from "recharts";
import { analyticsApi, type OverviewStats, type TrendPoint, type BestSeller, type InventoryByMake } from "../api/client";
import StatCard from "../components/StatCard";

export default function Analytics() {
  const [overview, setOverview] = useState<OverviewStats | null>(null);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [bestSellers, setBestSellers] = useState<BestSeller[]>([]);
  const [inventory, setInventory] = useState<InventoryByMake[]>([]);
  const [make, setMake] = useState("");
  const [model, setModel] = useState("");
  const [period, setPeriod] = useState(90);

  useEffect(() => {
    analyticsApi.overview().then((r) => setOverview(r.data));
    analyticsApi.inventoryByMake().then((r) => setInventory(r.data.slice(0, 15)));
  }, []);

  useEffect(() => {
    const params: Record<string, unknown> = { period };
    if (make) params.make = make;
    if (model) params.model = model;
    analyticsApi.priceTrend(params).then((r) => setTrend(r.data));
    analyticsApi.bestSellers({ period }).then((r) => setBestSellers(r.data));
  }, [make, model, period]);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Market Analytics</h1>

      {/* Overview KPIs */}
      {overview && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <StatCard label="Active listings" value={overview.total_active.toLocaleString()} />
          <StatCard label="Total in DB" value={overview.total_vehicles.toLocaleString()} />
          <StatCard label="New today" value={overview.new_today} color="text-green-600" />
          <StatCard label="Sold today" value={overview.sold_today} color="text-orange-500" />
          <StatCard
            label="Avg days to sell"
            value={overview.avg_days_to_sell?.toFixed(1) ?? "—"}
            sub="all time, deactivated"
            color="text-purple-600"
          />
          <StatCard label="Total inactive" value={overview.total_inactive.toLocaleString()} color="text-gray-500" />
        </div>
      )}

      {/* Filters for trend chart */}
      <div className="flex flex-wrap gap-3 items-center bg-white rounded-lg border p-4">
        <input
          className="border rounded px-2 py-1.5 text-sm"
          placeholder="Make (e.g. Toyota)"
          value={make}
          onChange={(e) => setMake(e.target.value)}
        />
        <input
          className="border rounded px-2 py-1.5 text-sm"
          placeholder="Model"
          value={model}
          onChange={(e) => setModel(e.target.value)}
        />
        <select
          className="border rounded px-2 py-1.5 text-sm"
          value={period}
          onChange={(e) => setPeriod(Number(e.target.value))}
        >
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
          <option value={180}>Last 180 days</option>
          <option value={365}>Last year</option>
        </select>
      </div>

      {/* Price trend chart */}
      <div className="bg-white rounded-lg border p-4">
        <h2 className="font-semibold mb-4 text-gray-700">
          Price Trend {make ? `— ${make}${model ? ` ${model}` : ""}` : "(all makes)"}
        </h2>
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={trend} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="period" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v: number) => `${v?.toLocaleString()} AZN`} />
            <Legend />
            <Line type="monotone" dataKey="avg_price" name="Avg Price" stroke="#2563eb" dot={false} strokeWidth={2} />
            <Line type="monotone" dataKey="median_price" name="Median Price" stroke="#16a34a" dot={false} strokeWidth={2} strokeDasharray="4 2" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Best sellers */}
        <div className="bg-white rounded-lg border p-4">
          <h2 className="font-semibold mb-3 text-gray-700">Best Sellers (Most Sold)</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-500 uppercase border-b">
                  <th className="py-1 text-left">Make / Model</th>
                  <th className="py-1 text-right">Sold</th>
                  <th className="py-1 text-right">Avg Days</th>
                  <th className="py-1 text-right">Avg Price</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {bestSellers.map((b, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="py-1.5 font-medium">{b.make} {b.model}</td>
                    <td className="py-1.5 text-right text-green-600 font-medium">{b.total_sold}</td>
                    <td className="py-1.5 text-right">{b.avg_days_to_sell?.toFixed(1) ?? "—"}</td>
                    <td className="py-1.5 text-right">{b.avg_price_azn ? `${Math.round(b.avg_price_azn).toLocaleString()}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Inventory by make */}
        <div className="bg-white rounded-lg border p-4">
          <h2 className="font-semibold mb-3 text-gray-700">Inventory by Make (Top 15)</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={inventory} layout="vertical" margin={{ left: 60, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis type="number" tick={{ fontSize: 11 }} />
              <YAxis dataKey="make" type="category" tick={{ fontSize: 11 }} width={60} />
              <Tooltip />
              <Legend />
              <Bar dataKey="active_count" name="Active" fill="#2563eb" stackId="a" />
              <Bar dataKey="inactive_count" name="Sold/Removed" fill="#d1d5db" stackId="a" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
