import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { sellersApi, type Vehicle, type PagedResponse } from "../api/client";

interface Seller {
  id: number;
  name: string | null;
  seller_type: string | null;
  city: string | null;
  phones: string[];
  total_listings: number;
  total_sold: number;
  avg_days_to_sell: number | null;
  first_seen: string;
  profile_url: string | null;
}

export default function SellerProfile() {
  const { id } = useParams<{ id: string }>();
  const [seller, setSeller] = useState<Seller | null>(null);
  const [vehicles, setVehicles] = useState<PagedResponse<Vehicle> | null>(null);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("active");

  useEffect(() => {
    if (!id) return;
    sellersApi.get(Number(id)).then((r) => setSeller(r.data as Seller));
  }, [id]);

  useEffect(() => {
    if (!id) return;
    sellersApi.vehicles(Number(id), { status, page, page_size: 50 })
      .then((r) => setVehicles(r.data as PagedResponse<Vehicle>));
  }, [id, status, page]);

  if (!seller) return <div className="p-8 text-center text-gray-400">Loading...</div>;

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link to="/" className="hover:underline">Vehicles</Link>
        <span>›</span>
        <span>Seller Profile</span>
      </div>

      <div className="bg-white rounded-lg border p-6">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold">{seller.name ?? "Unknown Seller"}</h1>
            <p className="text-gray-500 mt-1">
              {seller.seller_type === "dealer" ? "🏢 Dealer" : "👤 Private"} · {seller.city ?? "Unknown city"}
            </p>
            {seller.phones.length > 0 && (
              <p className="text-sm text-gray-600 mt-2">{seller.phones.join(" · ")}</p>
            )}
            {seller.profile_url && (
              <a href={seller.profile_url} target="_blank" rel="noopener noreferrer"
                className="text-sm text-blue-600 hover:underline mt-1 block">
                View on turbo.az →
              </a>
            )}
          </div>
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <p className="text-2xl font-bold text-blue-600">{seller.total_listings.toLocaleString()}</p>
              <p className="text-xs text-gray-500">Total listings</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-green-600">{seller.total_sold.toLocaleString()}</p>
              <p className="text-xs text-gray-500">Sold</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-purple-600">{seller.avg_days_to_sell?.toFixed(1) ?? "—"}</p>
              <p className="text-xs text-gray-500">Avg days to sell</p>
            </div>
          </div>
        </div>
      </div>

      {/* Vehicle list */}
      <div className="flex gap-3 items-center">
        <select
          value={status}
          onChange={(e) => { setStatus(e.target.value); setPage(1); }}
          className="border rounded px-2 py-1.5 text-sm"
        >
          <option value="active">Active</option>
          <option value="inactive">Sold / Inactive</option>
        </select>
        <span className="text-sm text-gray-500">{vehicles?.total.toLocaleString()} vehicles</span>
      </div>

      <div className="bg-white rounded-lg border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              {["Make / Model", "Year", "Price (AZN)", "Odometer", "Status", "Added", "Days to sell"].map((h) => (
                <th key={h} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y">
            {vehicles?.items.map((v) => (
              <tr key={v.id} className="hover:bg-gray-50">
                <td className="px-3 py-2">
                  <Link to={`/vehicles/${v.turbo_id}`} className="text-blue-600 hover:underline font-medium">
                    {v.make} {v.model}
                  </Link>
                </td>
                <td className="px-3 py-2">{v.year ?? "—"}</td>
                <td className="px-3 py-2 font-medium">{v.price_azn ? Math.round(v.price_azn).toLocaleString() : "—"}</td>
                <td className="px-3 py-2">{v.odometer ? `${v.odometer.toLocaleString()} ${v.odometer_type ?? ""}` : "—"}</td>
                <td className="px-3 py-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${v.status === "active" ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-600"}`}>
                    {v.status}
                  </span>
                </td>
                <td className="px-3 py-2 text-gray-500">{v.date_added.slice(0, 10)}</td>
                <td className="px-3 py-2 text-center">{v.days_to_sell ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {vehicles && vehicles.pages > 1 && (
        <div className="flex justify-center gap-2">
          <button disabled={page === 1} onClick={() => setPage(p => p - 1)}
            className="px-3 py-1.5 border rounded text-sm disabled:opacity-40 hover:bg-gray-100">← Prev</button>
          <span className="px-3 py-1.5 text-sm">{page} / {vehicles.pages}</span>
          <button disabled={page === vehicles.pages} onClick={() => setPage(p => p + 1)}
            className="px-3 py-1.5 border rounded text-sm disabled:opacity-40 hover:bg-gray-100">Next →</button>
        </div>
      )}
    </div>
  );
}
