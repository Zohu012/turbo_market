import { useEffect, useState } from "react";
import { vehiclesApi, type FeatureOption } from "../../api/client";
import { AnalyticsFilters } from "../../hooks/useAnalyticsFilters";
import { useMakeModelOptions } from "../../hooks/useMakeModelOptions";
import { AZ } from "../../i18n/az";
import SearchableSelect from "../SearchableSelect";

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

const dateInp = (value: string, onChange: (v: string) => void, label: string) => (
  <div className="flex flex-col gap-0.5">
    <span className="text-xs text-gray-500 leading-none">{label}</span>
    <input
      type="date"
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
      className="border rounded px-2 py-1.5 text-sm w-full"
    />
  </div>
);

const BOOL_OPTS = [
  { value: "true", label: "Bəli" },
  { value: "false", label: "Xeyr" },
];

export default function AnalyticsFilterForm({ filters, setFilters }: Props) {
  const { makes, models } = useMakeModelOptions(filters.make ?? "");
  const [featureOptions, setFeatureOptions] = useState<FeatureOption[]>([]);
  const [featureSearch, setFeatureSearch] = useState("");
  const [featuresOpen, setFeaturesOpen] = useState(false);

  const [years, setYears] = useState<string[]>([]);
  const [colors, setColors] = useState<string[]>([]);
  const [conditions, setConditions] = useState<string[]>([]);
  const [marketOptions, setMarketOptions] = useState<string[]>([]);
  const [cityOptions, setCityOptions] = useState<string[]>([]);

  useEffect(() => {
    vehiclesApi.features().then((r) => setFeatureOptions(r.data)).catch(() => {});
    vehiclesApi.years().then((r) => setYears(r.data.map(String))).catch(() => {});
    vehiclesApi.colors().then((r) => setColors(r.data)).catch(() => {});
    vehiclesApi.conditions().then((r) => setConditions(r.data)).catch(() => {});
    vehiclesApi.marketOptions().then((r) => setMarketOptions(r.data)).catch(() => {});
    vehiclesApi.cities().then((r) => setCityOptions(r.data)).catch(() => {});
  }, []);

  const set = (key: keyof AnalyticsFilters) => (value: string) =>
    setFilters({ [key]: value || undefined });

  const selectedFeatureIds = filters.features
    ? filters.features.split(",").map(Number).filter(Boolean)
    : [];

  const toggleFeature = (id: number) => {
    const next = selectedFeatureIds.includes(id)
      ? selectedFeatureIds.filter((x) => x !== id)
      : [...selectedFeatureIds, id];
    setFilters({ features: next.length ? next.join(",") : undefined }, true);
  };

  const filteredFeatures = featureOptions.filter((f) =>
    f.name.toLowerCase().includes(featureSearch.toLowerCase())
  );

  return (
    <div className="space-y-4">
      {/* Vehicle section */}
      <div>
        <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Avtomobil
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2">
          <SearchableSelect
            value={filters.make ?? ""}
            onChange={(v) => setFilters({ make: v || undefined }, true)}
            placeholder={AZ.filters.allMakes}
            options={makes.map((m) => ({ value: m, label: m }))}
          />
          <SearchableSelect
            value={filters.model ?? ""}
            onChange={(v) => setFilters({ model: v || undefined }, true)}
            placeholder={AZ.filters.allModels}
            options={models.map((m) => ({ value: m, label: m }))}
          />
          <SearchableSelect
            value={filters.year_min ?? ""}
            onChange={(v) => setFilters({ year_min: v || undefined }, true)}
            placeholder={AZ.filters.yearFrom}
            options={years.map((y) => ({ value: y, label: y }))}
          />
          <SearchableSelect
            value={filters.year_max ?? ""}
            onChange={(v) => setFilters({ year_max: v || undefined }, true)}
            placeholder={AZ.filters.yearTo}
            options={years.map((y) => ({ value: y, label: y }))}
          />
          {sel(filters.body_type ?? "", set("body_type"), AZ.filters.bodyType, AZ.options.bodyTypes)}
          {sel(filters.fuel_type ?? "", set("fuel_type"), AZ.filters.fuelType, AZ.options.fuelTypes)}
          {sel(filters.transmission ?? "", set("transmission"), AZ.filters.transmission, AZ.options.transmissions)}
          {inp(filters.engine_min ?? "", set("engine_min"), "Həcm min (sm³)", "number")}
          {inp(filters.engine_max ?? "", set("engine_max"), "Həcm max (sm³)", "number")}
          {inp(filters.hp_min ?? "", set("hp_min"), AZ.filters.hpFrom, "number")}
          {inp(filters.hp_max ?? "", set("hp_max"), AZ.filters.hpTo, "number")}
          {inp(filters.odometer_min ?? "", set("odometer_min"), AZ.filters.odometerFrom, "number")}
          {inp(filters.odometer_max ?? "", set("odometer_max"), AZ.filters.odometerTo, "number")}
          <SearchableSelect
            value={filters.color ?? ""}
            onChange={(v) => setFilters({ color: v || undefined }, true)}
            placeholder={AZ.filters.color}
            options={colors.map((c) => ({ value: c, label: c }))}
          />
          <SearchableSelect
            value={filters.condition ?? ""}
            onChange={(v) => setFilters({ condition: v || undefined }, true)}
            placeholder={AZ.filters.condition}
            options={conditions.map((c) => ({ value: c, label: c }))}
          />
          <SearchableSelect
            value={filters.market_for ?? ""}
            onChange={(v) => setFilters({ market_for: v || undefined }, true)}
            placeholder={AZ.filters.market}
            options={marketOptions.map((m) => ({ value: m, label: m }))}
          />
          {sel(filters.is_new ?? "", set("is_new"), AZ.filters.isNew, BOOL_OPTS)}
          {sel(filters.is_on_order ?? "", set("is_on_order"), AZ.filters.isOrder, BOOL_OPTS)}
        </div>
      </div>

      {/* Market section */}
      <div>
        <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Bazar
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2">
          <SearchableSelect
            value={filters.city ?? ""}
            onChange={(v) => setFilters({ city: v || undefined }, true)}
            placeholder={AZ.filters.city}
            options={cityOptions.map((c) => ({ value: c, label: c }))}
          />
          {inp(filters.price_min ?? "", set("price_min"), AZ.filters.priceFrom, "number")}
          {inp(filters.price_max ?? "", set("price_max"), AZ.filters.priceTo, "number")}
          {sel(filters.seller_type ?? "", set("seller_type"), AZ.filters.sellerType,
            AZ.options.sellerTypes)}
          {sel(filters.credit ?? "", set("credit"), AZ.filters.isCredit, BOOL_OPTS)}
          {sel(filters.barter ?? "", set("barter"), AZ.filters.isBarter, BOOL_OPTS)}
          {sel(filters.status ?? "", set("status"), AZ.filters.status, AZ.options.statuses)}
        </div>
      </div>

      {/* Dates section */}
      <div>
        <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Tarixlər
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2">
          {dateInp(filters.date_from ?? "", set("date_from"), AZ.filters.dateFrom)}
          {dateInp(filters.date_to ?? "", set("date_to"), AZ.filters.dateTo)}
          {dateInp(filters.date_sold_from ?? "", set("date_sold_from"), AZ.filters.dateSoldFrom)}
          {dateInp(filters.date_sold_to ?? "", set("date_sold_to"), AZ.filters.dateSoldTo)}
        </div>
      </div>

      {/* Features section */}
      {featureOptions.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setFeaturesOpen((v) => !v)}
            className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2 flex items-center gap-1 hover:text-gray-700"
          >
            {AZ.filters.features}
            {selectedFeatureIds.length > 0 && (
              <span className="ml-1 bg-blue-100 text-blue-700 rounded-full px-1.5 text-xs">
                {selectedFeatureIds.length}
              </span>
            )}
            <span className="text-gray-400 ml-1">{featuresOpen ? "▲" : "▼"}</span>
          </button>
          {featuresOpen && (
            <div>
              <input
                type="text"
                placeholder="Xüsusiyyət axtar..."
                value={featureSearch}
                onChange={(e) => setFeatureSearch(e.target.value)}
                className="border rounded px-2 py-1.5 text-sm w-full mb-2"
              />
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-1 max-h-40 overflow-y-auto">
                {filteredFeatures.map((f) => (
                  <label key={f.id} className="flex items-center gap-1.5 text-sm cursor-pointer hover:bg-gray-50 rounded px-1 py-0.5">
                    <input
                      type="checkbox"
                      checked={selectedFeatureIds.includes(f.id)}
                      onChange={() => toggleFeature(f.id)}
                      className="rounded"
                    />
                    <span className="truncate">{f.name}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
