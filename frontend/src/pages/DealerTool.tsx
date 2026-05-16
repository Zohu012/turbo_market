import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { vehiclesApi, type Vehicle, type PagedResponse, type VehicleKpis } from "../api/client";
import FilterBar, { defaultFilters, type Filters } from "../components/FilterBar";

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

function filtersToParams(f: Filters): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  const keys = Object.keys(f) as (keyof Filters)[];
  for (const k of keys) {
    if (f[k] !== "" && f[k] !== undefined) {
      // split sort_by / sort_dir from the compound key
      if (k === "sort_by" || k === "sort_dir") {
        params[k] = f[k];
      } else {
        params[k] = f[k];
      }
    }
  }
  return params;
}

export default function DealerTool() {
  const [filters, setFilters] = useState<Filters>(defaultFilters);
  const [data, setData] = useState<PagedResponse<Vehicle> | null>(null);
  const [kpis, setKpis] = useState<VehicleKpis | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (f: Filters, p: number) => {
    setLoading(true);
    try {
      const params = { ...filtersToParams(f), page: p, page_size: 50 };
      const [listRes, kpisRes] = await Promise.all([
        vehiclesApi.list(params),
        vehiclesApi.kpis(filtersToParams(f)),
      ]);
      setData(listRes.data);
      setKpis(kpisRes.data);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setPage(1);
    load(filters, 1);
  }, [filters, load]);

  useEffect(() => {
    load(filters, page);
  }, [page]); // eslint-disable-line

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Vehicle Inventory</h1>
      <FilterBar filters={filters} onChange={(f) => { setFilters(f); setPage(1); }} />

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
                {["Photo", "Make / Model", "Year", "Price (AZN)", "Odometer", "Color", "Fuel", "Gearbox", "City", "Status", "Added", "Days to sell"].map((h) => (
                  <th key={h} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wide whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {loading ? (
                <tr><td colSpan={12} className="px-4 py-8 text-center text-gray-400">Loading...</td></tr>
              ) : data?.items.length === 0 ? (
                <tr><td colSpan={12} className="px-4 py-8 text-center text-gray-400">No vehicles found</td></tr>
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
                      <Link to={`/vehicles/${v.turbo_id}`} className="font-medium text-blue-600 hover:underline">
                        {v.make} {v.model}
                      </Link>
                    </td>
                    <td className="px-3 py-2">{v.year ?? "—"}</td>
                    <td className="px-3 py-2 font-medium">{fmt(v.price_azn)}</td>
                    <td className="px-3 py-2">{v.odometer ? `${v.odometer.toLocaleString()} ${v.odometer_type ?? ""}` : "—"}</td>
                    <td className="px-3 py-2">{v.color ?? "—"}</td>
                    <td className="px-3 py-2">{v.fuel_type ?? "—"}</td>
                    <td className="px-3 py-2">{v.transmission ?? "—"}</td>
                    <td className="px-3 py-2">{v.city ?? "—"}</td>
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
