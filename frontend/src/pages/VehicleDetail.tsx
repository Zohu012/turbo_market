import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { vehiclesApi, type Vehicle } from "../api/client";

export default function VehicleDetail() {
  const { turboId } = useParams<{ turboId: string }>();
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [selectedImg, setSelectedImg] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!turboId) return;
    setLoading(true);
    vehiclesApi.get(Number(turboId))
      .then((r) => setVehicle(r.data))
      .finally(() => setLoading(false));
  }, [turboId]);

  if (loading) return <div className="p-8 text-center text-gray-400">Loading...</div>;
  if (!vehicle) return <div className="p-8 text-center text-red-400">Vehicle not found</div>;

  const extra = vehicle as unknown as Record<string, unknown>;
  const specs: Array<[string, unknown]> = [
    ["Year", vehicle.year],
    ["Color", vehicle.color],
    ["Engine", vehicle.engine],
    ["Fuel", vehicle.fuel_type],
    ["Transmission", vehicle.transmission],
    ["Body", vehicle.body_type],
    ["Drive", extra.drive_type],
    ["Doors", extra.doors],
    ["Odometer", vehicle.odometer ? `${vehicle.odometer.toLocaleString()} ${vehicle.odometer_type ?? ""}` : null],
    ["VIN", extra.vin],
    ["City", vehicle.city],
  ];
  const visibleSpecs = specs.filter(([, v]) => v != null);

  const priceHistory = vehicle.price_history ?? [];

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link to="/" className="hover:underline">Vehicles</Link>
        <span>›</span>
        <span>{vehicle.make} {vehicle.model}</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Images */}
        <div>
          <div className="rounded-lg overflow-hidden bg-gray-100 aspect-[4/3]">
            {vehicle.images && vehicle.images.length > 0 ? (
              <img
                src={vehicle.images[selectedImg]?.url}
                alt=""
                className="w-full h-full object-cover"
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-gray-300">No images</div>
            )}
          </div>
          {vehicle.images && vehicle.images.length > 1 && (
            <div className="flex gap-2 mt-2 overflow-x-auto">
              {vehicle.images.map((img, i) => (
                <img
                  key={img.id}
                  src={img.url}
                  alt=""
                  onClick={() => setSelectedImg(i)}
                  className={`w-16 h-12 object-cover rounded cursor-pointer border-2 flex-shrink-0 ${i === selectedImg ? "border-blue-500" : "border-transparent"}`}
                />
              ))}
            </div>
          )}
        </div>

        {/* Main info */}
        <div className="space-y-4">
          <div>
            <h1 className="text-2xl font-bold">{vehicle.make} {vehicle.model} {vehicle.year}</h1>
            <p className="text-3xl font-bold text-blue-600 mt-1">
              {vehicle.price?.toLocaleString()} {vehicle.currency}
              {vehicle.currency !== "AZN" && vehicle.price_azn && (
                <span className="text-base font-normal text-gray-400 ml-2">
                  ≈ {Math.round(vehicle.price_azn).toLocaleString()} AZN
                </span>
              )}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2">
            {visibleSpecs.map(([label, value]) => (
              <div key={label} className="bg-gray-50 rounded p-2">
                <p className="text-xs text-gray-500">{label}</p>
                <p className="text-sm font-medium">{String(value)}</p>
              </div>
            ))}
          </div>

          <div className="flex gap-3">
            <span className={`text-sm px-3 py-1 rounded-full font-medium ${vehicle.status === "active" ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-600"}`}>
              {vehicle.status}
            </span>
            {vehicle.days_to_sell != null && (
              <span className="text-sm px-3 py-1 rounded-full bg-purple-100 text-purple-700 font-medium">
                Sold in {vehicle.days_to_sell} days
              </span>
            )}
          </div>

          <div className="text-sm text-gray-500 space-y-1">
            <p>Added: {vehicle.date_added.slice(0, 10)}</p>
            {vehicle.date_deactivated && <p>Deactivated: {vehicle.date_deactivated.slice(0, 10)}</p>}
          </div>

          <a
            href={vehicle.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
          >
            View on turbo.az →
          </a>
        </div>
      </div>

      {/* Seller */}
      {vehicle.seller ? (
        <div className="bg-white rounded-lg border p-4">
          <h2 className="font-semibold mb-2">Seller</h2>
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium">{vehicle.seller.name ?? "Unknown"}</p>
              <p className="text-sm text-gray-500">{vehicle.seller.seller_type} · {vehicle.seller.city}</p>
              <p className="text-xs text-gray-400 mt-1">
                {vehicle.seller.total_listings} listings · {vehicle.seller.total_sold} sold
              </p>
            </div>
            <Link to={`/sellers/${vehicle.seller.id}`} className="text-sm text-blue-600 hover:underline">
              View profile →
            </Link>
          </div>
        </div>
      ) : null}

      {/* Description */}
      {extra.description ? (
        <div className="bg-white rounded-lg border p-4">
          <h2 className="font-semibold mb-2">Description</h2>
          <p className="text-sm text-gray-600 whitespace-pre-line">
            {String(extra.description)}
          </p>
        </div>
      ) : null}

      {/* Price history */}
      {priceHistory.length > 0 && (
        <div className="bg-white rounded-lg border p-4">
          <h2 className="font-semibold mb-3">Price History</h2>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={priceHistory.slice().reverse()}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="recorded_at" tickFormatter={(v: string) => v.slice(0, 10)} tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: number) => `${v?.toLocaleString()} AZN`} labelFormatter={(l: string) => l.slice(0, 10)} />
              <Line type="stepAfter" dataKey="price_azn" stroke="#2563eb" dot={true} strokeWidth={2} name="Price AZN" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
