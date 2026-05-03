import { AnalyticsFilters } from "../../hooks/useAnalyticsFilters";
import { useMakeModelOptions } from "../../hooks/useMakeModelOptions";
import { AZ } from "../../i18n/az";

interface Props {
  filters: AnalyticsFilters;
  setFilters: (partial: Partial<AnalyticsFilters>, immediate?: boolean) => void;
}

const sel = (
  value: string,
  onChange: (v: string) => void,
  placeholder: string,
  opts: string[] | Array<{ value: string; label: string }>,
) => (
  <select
    value={value ?? ""}
    onChange={(e) => onChange(e.target.value)}
    className="border rounded px-2 py-1.5 text-sm bg-white w-full"
  >
    <option value="">{placeholder}</option>
    {opts.map((o) =>
      typeof o === "string" ? (
        <option key={o} value={o}>{o}</option>
      ) : (
        <option key={o.value} value={o.value}>{o.label}</option>
      ),
    )}
  </select>
);

const inp = (
  value: string,
  onChange: (v: string) => void,
  placeholder: string,
  type = "text",
) => (
  <input
    type={type}
    placeholder={placeholder}
    value={value ?? ""}
    onChange={(e) => onChange(e.target.value)}
    className="border rounded px-2 py-1.5 text-sm w-full"
  />
);

export default function AnalyticsFilterForm({ filters, setFilters }: Props) {
  const { makes, models } = useMakeModelOptions(filters.make ?? "");

  const set = (key: keyof AnalyticsFilters) => (value: string) =>
    setFilters({ [key]: value || undefined });

  return (
    <div className="space-y-4">
      {/* Vehicle section */}
      <div>
        <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Avtomobil
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2">
          {sel(filters.make ?? "", set("make"), AZ.filters.allMakes,
            makes.map((m) => ({ value: m, label: m })))}
          {sel(filters.model ?? "", set("model"), AZ.filters.allModels,
            models.map((m) => ({ value: m, label: m })))}
          {inp(filters.year_min ?? "", set("year_min"), AZ.filters.yearFrom, "number")}
          {inp(filters.year_max ?? "", set("year_max"), AZ.filters.yearTo, "number")}
          {sel(filters.body_type ?? "", set("body_type"), AZ.filters.bodyType, AZ.options.bodyTypes)}
          {sel(filters.fuel_type ?? "", set("fuel_type"), AZ.filters.fuelType, AZ.options.fuelTypes)}
          {sel(filters.transmission ?? "", set("transmission"), AZ.filters.transmission, AZ.options.transmissions)}
          {inp(filters.hp_min ?? "", set("hp_min"), AZ.filters.hpFrom, "number")}
          {inp(filters.hp_max ?? "", set("hp_max"), AZ.filters.hpTo, "number")}
          {inp(filters.odometer_min ?? "", set("odometer_min"), AZ.filters.odometerFrom, "number")}
          {inp(filters.odometer_max ?? "", set("odometer_max"), AZ.filters.odometerTo, "number")}
          {inp(filters.color ?? "", set("color"), AZ.filters.color)}
        </div>
      </div>

      {/* Market section */}
      <div>
        <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Bazar
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2">
          {inp(filters.city ?? "", set("city"), AZ.filters.city)}
          {inp(filters.price_min ?? "", set("price_min"), AZ.filters.priceFrom, "number")}
          {inp(filters.price_max ?? "", set("price_max"), AZ.filters.priceTo, "number")}
          {sel(filters.seller_type ?? "", set("seller_type"), AZ.filters.sellerType,
            AZ.options.sellerTypes)}
          {sel(filters.status ?? "", set("status"), AZ.filters.status, AZ.options.statuses)}
          {inp(filters.date_from ?? "", set("date_from"), AZ.filters.dateFrom, "date")}
          {inp(filters.date_to ?? "", set("date_to"), AZ.filters.dateTo, "date")}
        </div>
      </div>
    </div>
  );
}
