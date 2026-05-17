import { useEffect, useMemo, useState } from "react";
import { vehiclesApi, type Vehicle, type PagedResponse, type VehicleKpis } from "../api/client";
import FilterBar from "../components/FilterBar";
import { useInventoryFilters } from "../hooks/useInventoryFilters";

const fmt = (n: number | null | undefined, currency?: string | null) =>
  n == null ? "—" : `${Math.round(n).toLocaleString()} ${currency ?? "AZN"}`;

const fmtDays = (n: number | null | undefined) =>
  n == null ? "—" : `${n} gün`;

function KpiCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white rounded-lg border px-3 py-2">
      <div className="text-xs text-gray-500 truncate">{label}</div>
      <div className="text-base font-semibold text-gray-800 mt-0.5 truncate">{value}</div>
    </div>
  );
}

const Th = ({ children }: { children: React.ReactNode }) => (
  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wide whitespace-nowrap">
    {children}
  </th>
);

export default function DealerTool() {
  const { filters, setFilters, resetFilters, toParams } = useInventoryFilters();
  const [data, setData] = useState<PagedResponse<Vehicle> | null>(null);
  const [kpis, setKpis] = useState<VehicleKpis | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);

  const params = toParams();
  const paramsKey = useMemo(() => JSON.stringify(params), [params]); // eslint-disable-line

  useEffect(() => { setPage(1); }, [paramsKey]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      vehiclesApi.list({ ...params, page, page_size: 50 }),
      vehiclesApi.kpis(params),
    ]).then(([listRes, kpisRes]) => {
      if (!cancelled) {
        setData(listRes.data);
        setKpis(kpisRes.data);
      }
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [paramsKey, page]); // eslint-disable-line

  const toggleSort = (col: string) => {
    const dir = filters.sort_by === col && filters.sort_dir === "asc" ? "desc" : "asc";
    setFilters({ sort_by: col, sort_dir: dir }, true);
  };

  const SortTh = ({ col, label }: { col: string; label: string }) => (
    <th
      className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wide whitespace-nowrap cursor-pointer select-none hover:bg-gray-100"
      onClick={() => toggleSort(col)}
    >
      {label}{" "}
      {filters.sort_by === col
        ? (filters.sort_dir === "asc" ? "↑" : "↓")
        : <span className="text-gray-300">↕</span>}
    </th>
  );

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Vehicle Inventory</h1>
      <FilterBar filters={filters} setFilters={setFilters} resetFilters={resetFilters} />

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2 mb-4">
        <KpiCard label="Ort. qiymət" value={fmt(kpis?.avg_price)} />
        <KpiCard label="Median qiymət" value={fmt(kpis?.median_price)} />
        <KpiCard label="Min qiymət" value={fmt(kpis?.min_price)} />
        <KpiCard label="Max qiymət" value={fmt(kpis?.max_price)} />
        <KpiCard label="Ort. satış müddəti" value={fmtDays(kpis?.avg_dts)} />
        <KpiCard label="Median satış müddəti" value={fmtDays(kpis?.median_dts)} />
        <KpiCard label="Min satış müddəti" value={fmtDays(kpis?.min_dts)} />
        <KpiCard label="Max satış müddəti" value={fmtDays(kpis?.max_dts)} />
        <KpiCard label="Satış (7 gün)" value={kpis?.sales_7d?.toLocaleString() ?? "—"} />
        <KpiCard label="Satış (30 gün)" value={kpis?.sales_30d?.toLocaleString() ?? "—"} />
        <KpiCard label="Aktiv elanlar" value={kpis?.total_active?.toLocaleString() ?? "—"} />
        <KpiCard label="Satılmış elanlar" value={kpis?.total_sold?.toLocaleString() ?? "—"} />
      </div>

      {/* Results summary */}
      <div className="flex items-center justify-between mb-3 text-sm text-gray-500">
        <span>{data ? `${data.total.toLocaleString()} vehicles` : "Loading..."}</span>
        <span>{data ? `Page ${data.page} / ${data.pages}` : ""}</span>
      </div>

      {/* Table */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <Th>Photo</Th>
                <Th>Make / Model</Th>
                <SortTh col="year" label="Year" />
                <SortTh col="price_azn" label="Price (AZN)" />
                <SortTh col="odometer" label="Odometer" />
                <Th>Color</Th>
                <Th>Fuel</Th>
                <Th>Gearbox</Th>
                <Th>City</Th>
                <Th>Satıcı</Th>
                <Th>Status</Th>
                <SortTh col="date_added" label="Added" />
                <SortTh col="days_to_sell" label="Days to sell" />
              </tr>
            </thead>
            <tbody className="divide-y">
              {loading ? (
                <tr><td colSpan={13} className="px-4 py-8 text-center text-gray-400">Loading...</td></tr>
              ) : data?.items.length === 0 ? (
                <tr><td colSpan={13} className="px-4 py-8 text-center text-gray-400">No vehicles found</td></tr>
              ) : (
                data?.items.map((v) => (
                  <tr key={v.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-3 py-2">
                      {v.primary_image ? (
                        <img src={v.primary_image} alt="" className="w-16 h-12 object-cover rounded" />
                      ) : (
                        <div className="w-16 h-12 bg-gray-100 rounded flex items-center justify-center text-gray-300 text-xs">No img</div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <a
                        href={`/vehicles/${v.turbo_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-medium text-blue-600 hover:underline"
                      >
                        {v.make} {v.model}
                      </a>
                    </td>
                    <td className="px-3 py-2">{v.year ?? "—"}</td>
                    <td className="px-3 py-2 font-medium">{fmt(v.price_azn)}</td>
                    <td className="px-3 py-2">{v.odometer ? `${v.odometer.toLocaleString()} ${v.odometer_type ?? ""}` : "—"}</td>
                    <td className="px-3 py-2">{v.color ?? "—"}</td>
                    <td className="px-3 py-2">{v.fuel_type ?? "—"}</td>
                    <td className="px-3 py-2">{v.transmission ?? "—"}</td>
                    <td className="px-3 py-2">{v.city ?? "—"}</td>
                    <td className="px-3 py-2">
                      {v.seller ? (
                        <div className="min-w-[120px]">
                          <a
                            href={`/sellers/${v.seller.id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-600 hover:underline text-xs font-medium"
                          >
                            {v.seller.name ?? "—"}
                          </a>
                          {v.seller.phones.map((p) => (
                            <div key={p} className="text-xs text-gray-500">{p}</div>
                          ))}
                        </div>
                      ) : "—"}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${v.status === "active" ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-600"}`}>
                        {v.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-gray-500">{v.date_added.slice(0, 10)}</td>
                    <td className="px-3 py-2 text-center">{v.days_to_sell ?? "—"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      {data && data.pages > 1 && (
        <div className="flex justify-center gap-2 mt-4">
          <button
            disabled={page === 1}
            onClick={() => setPage((p) => p - 1)}
            className="px-3 py-1.5 border rounded text-sm disabled:opacity-40 hover:bg-gray-100"
          >
            ← Prev
          </button>
          <span className="px-3 py-1.5 text-sm text-gray-600">
            {page} / {data.pages}
          </span>
          <button
            disabled={page === data.pages}
            onClick={() => setPage((p) => p + 1)}
            className="px-3 py-1.5 border rounded text-sm disabled:opacity-40 hover:bg-gray-100"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
