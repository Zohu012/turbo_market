import { useMakeModelOptions } from "../hooks/useMakeModelOptions";

export interface Filters {
  make: string;
  model: string;
  year_min: string;
  year_max: string;
  price_min: string;
  price_max: string;
  odometer_max: string;
  color: string;
  fuel_type: string;
  transmission: string;
  body_type: string;
  city: string;
  status: string;
  sort_by: string;
  sort_dir: string;
}

export const defaultFilters: Filters = {
  make: "", model: "", year_min: "", year_max: "",
  price_min: "", price_max: "", odometer_max: "",
  color: "", fuel_type: "", transmission: "",
  body_type: "", city: "", status: "active",
  sort_by: "date_added", sort_dir: "desc",
};

interface Props {
  filters: Filters;
  onChange: (f: Filters) => void;
}

export default function FilterBar({ filters, onChange }: Props) {
  const { makes, models } = useMakeModelOptions(filters.make);

  const set = (key: keyof Filters, value: string) =>
    onChange({ ...filters, [key]: value, ...(key === "make" ? { model: "" } : {}) });

  const sel = (key: keyof Filters, opts: string[], label: string) => (
    <select
      value={filters[key]}
      onChange={(e) => set(key, e.target.value)}
      className="border rounded px-2 py-1.5 text-sm bg-white w-full"
    >
      <option value="">{label}</option>
      {opts.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  );

  const inp = (key: keyof Filters, placeholder: string, type = "text") => (
    <input
      type={type}
      placeholder={placeholder}
      value={filters[key]}
      onChange={(e) => set(key, e.target.value)}
      className="border rounded px-2 py-1.5 text-sm w-full"
    />
  );

  return (
    <div className="bg-white rounded-lg border p-4 mb-4">
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8 gap-3">
        {sel("make", makes, "All Makes")}
        {sel("model", models, "All Models")}
        {inp("year_min", "Year from", "number")}
        {inp("year_max", "Year to", "number")}
        {inp("price_min", "Price min (AZN)", "number")}
        {inp("price_max", "Price max (AZN)", "number")}
        {inp("odometer_max", "Max km/mi", "number")}
        {inp("color", "Color")}
        {sel("fuel_type", ["Benzin", "Dizel", "Elektrik", "Hibrid", "Qaz"], "Fuel")}
        {sel("transmission", ["Avtomat", "Mexaniki", "Yarıavtomat"], "Gearbox")}
        {sel("body_type", ["Sedan", "Offroader / SUV", "Hetçbek", "Universal", "Kupé", "Kabriolet", "Pikap", "Furqon"], "Body")}
        {inp("city", "City")}
        {sel("status", ["active", "inactive"], "Status")}
        <select
          value={`${filters.sort_by}:${filters.sort_dir}`}
          onChange={(e) => {
            const [sort_by, sort_dir] = e.target.value.split(":");
            onChange({ ...filters, sort_by, sort_dir });
          }}
          className="border rounded px-2 py-1.5 text-sm bg-white w-full"
        >
          <option value="date_added:desc">Newest first</option>
          <option value="date_added:asc">Oldest first</option>
          <option value="price_azn:asc">Price ↑</option>
          <option value="price_azn:desc">Price ↓</option>
          <option value="year:desc">Year ↓</option>
          <option value="odometer:asc">Odometer ↑</option>
          <option value="days_to_sell:asc">Days to sell ↑</option>
        </select>
        <button
          onClick={() => onChange(defaultFilters)}
          className="border rounded px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 transition-colors"
        >
          Reset
        </button>
      </div>
    </div>
  );
}
