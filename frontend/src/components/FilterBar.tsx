import { useEffect, useState } from "react";
import { vehiclesApi, type FeatureOption } from "../api/client";
import { useMakeModelOptions } from "../hooks/useMakeModelOptions";

export interface Filters {
  // Vehicle
  make: string;
  model: string;
  year_min: string;
  year_max: string;
  body_type: string;
  fuel_type: string;
  transmission: string;
  engine_min: string;
  engine_max: string;
  hp_min: string;
  hp_max: string;
  color: string;
  condition: string;
  market_for: string;
  is_new: string;
  // Market
  city: string;
  price_min: string;
  price_max: string;
  odometer_min: string;
  odometer_max: string;
  seller_type: string;
  is_credit: string;
  is_barter: string;
  is_on_order: string;
  // Dates & Status
  date_added_from: string;
  date_added_to: string;
  date_sold_from: string;
  date_sold_to: string;
  days_to_sell_min: string;
  days_to_sell_max: string;
  status: string;
  sort_by: string;
  sort_dir: string;
  // Features (comma-separated IDs)
  features: string;
}

export const defaultFilters: Filters = {
  make: "", model: "",
  year_min: "", year_max: "",
  body_type: "", fuel_type: "", transmission: "",
  engine_min: "", engine_max: "",
  hp_min: "", hp_max: "",
  color: "", condition: "", market_for: "", is_new: "",
  city: "",
  price_min: "", price_max: "",
  odometer_min: "", odometer_max: "",
  seller_type: "", is_credit: "", is_barter: "", is_on_order: "",
  date_added_from: "", date_added_to: "",
  date_sold_from: "", date_sold_to: "",
  days_to_sell_min: "", days_to_sell_max: "",
  status: "active",
  sort_by: "date_added", sort_dir: "desc",
  features: "",
};

interface Props {
  filters: Filters;
  onChange: (f: Filters) => void;
}

const BODY_TYPES = ["Sedan", "Offroader / SUV", "Hetçbek", "Universal", "Kupé", "Kabriolet", "Pikap", "Furqon"];
const FUEL_TYPES = ["Benzin", "Dizel", "Elektrik", "Hibrid", "Qaz"];
const TRANSMISSIONS = ["Avtomat", "Mexaniki", "Yarıavtomat"];
const SELLER_TYPES = [
  { value: "business", label: "Avtosalon" },
  { value: "dealer", label: "Diler" },
  { value: "private", label: "Şəxsi" },
];
const BOOL_OPTS = [
  { value: "true", label: "Bəli" },
  { value: "false", label: "Xeyr" },
];

export default function FilterBar({ filters, onChange }: Props) {
  const { makes, models } = useMakeModelOptions(filters.make);
  const [featureOptions, setFeatureOptions] = useState<FeatureOption[]>([]);
  const [featureSearch, setFeatureSearch] = useState("");
  const [openSection, setOpenSection] = useState<string | null>("vehicle");

  useEffect(() => {
    vehiclesApi.features().then((r) => setFeatureOptions(r.data)).catch(() => {});
  }, []);

  const set = (key: keyof Filters, value: string) =>
    onChange({ ...filters, [key]: value, ...(key === "make" ? { model: "" } : {}) });

  const sel = (key: keyof Filters, opts: string[] | Array<{ value: string; label: string }>, label: string) => (
    <select
      value={filters[key]}
      onChange={(e) => set(key, e.target.value)}
      className="border rounded px-2 py-1.5 text-sm bg-white w-full"
    >
      <option value="">{label}</option>
      {opts.map((o) =>
        typeof o === "string" ? (
          <option key={o} value={o}>{o}</option>
        ) : (
          <option key={o.value} value={o.value}>{o.label}</option>
        )
      )}
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

  const selectedFeatureIds = filters.features
    ? filters.features.split(",").map(Number).filter(Boolean)
    : [];

  const toggleFeature = (id: number) => {
    const next = selectedFeatureIds.includes(id)
      ? selectedFeatureIds.filter((x) => x !== id)
      : [...selectedFeatureIds, id];
    set("features", next.join(","));
  };

  const filteredFeatures = featureOptions.filter((f) =>
    f.name.toLowerCase().includes(featureSearch.toLowerCase())
  );

  const SectionHeader = ({ id, title }: { id: string; title: string }) => (
    <button
      type="button"
      onClick={() => setOpenSection(openSection === id ? null : id)}
      className="w-full flex items-center justify-between text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2 hover:text-gray-700"
    >
      <span>{title}</span>
      <span className="text-gray-400">{openSection === id ? "▲" : "▼"}</span>
    </button>
  );

  return (
    <div className="bg-white rounded-lg border p-4 mb-4 space-y-3">

      {/* Vehicle section */}
      <div>
        <SectionHeader id="vehicle" title="Avtomobil" />
        {openSection === "vehicle" && (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2">
            {sel("make", makes.map((m) => ({ value: m, label: m })), "Bütün markalar")}
            {sel("model", models.map((m) => ({ value: m, label: m })), "Bütün modellər")}
            {inp("year_min", "İl (min)", "number")}
            {inp("year_max", "İl (max)", "number")}
            {sel("body_type", BODY_TYPES, "Ban növü")}
            {sel("fuel_type", FUEL_TYPES, "Yanacaq")}
            {sel("transmission", TRANSMISSIONS, "Sürətlər qutusu")}
            {inp("engine_min", "Həcm min (L)", "number")}
            {inp("engine_max", "Həcm max (L)", "number")}
            {inp("hp_min", "Güc min (HP)", "number")}
            {inp("hp_max", "Güc max (HP)", "number")}
            {inp("color", "Rəng")}
            {inp("condition", "Vəziyyət")}
            {inp("market_for", "Bazar")}
            {sel("is_new", BOOL_OPTS, "Yeni avtomobil")}
          </div>
        )}
      </div>

      {/* Market section */}
      <div>
        <SectionHeader id="market" title="Bazar" />
        {openSection === "market" && (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2">
            {inp("city", "Şəhər")}
            {inp("price_min", "Qiymət min (AZN)", "number")}
            {inp("price_max", "Qiymət max (AZN)", "number")}
            {inp("odometer_min", "Yürüş min (km)", "number")}
            {inp("odometer_max", "Yürüş max (km)", "number")}
            {sel("seller_type", SELLER_TYPES, "Satıcı növü")}
            {sel("is_credit", BOOL_OPTS, "Kredit var")}
            {sel("is_barter", BOOL_OPTS, "Barter var")}
            {sel("is_on_order", BOOL_OPTS, "Sifarişlə")}
          </div>
        )}
      </div>

      {/* Dates & Status section */}
      <div>
        <SectionHeader id="dates" title="Tarixlər və Status" />
        {openSection === "dates" && (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2">
            {inp("date_added_from", "Əlavə tarixi (başlanğıc)", "date")}
            {inp("date_added_to", "Əlavə tarixi (son)", "date")}
            {inp("date_sold_from", "Satış tarixi (başlanğıc)", "date")}
            {inp("date_sold_to", "Satış tarixi (son)", "date")}
            {inp("days_to_sell_min", "Satış günü (min)", "number")}
            {inp("days_to_sell_max", "Satış günü (max)", "number")}
            {sel("status", [{ value: "active", label: "Aktiv" }, { value: "inactive", label: "Deaktiv" }], "Status")}
            <select
              value={`${filters.sort_by}:${filters.sort_dir}`}
              onChange={(e) => {
                const [sort_by, sort_dir] = e.target.value.split(":");
                onChange({ ...filters, sort_by, sort_dir });
              }}
              className="border rounded px-2 py-1.5 text-sm bg-white w-full"
            >
              <option value="date_added:desc">Ən yeni əvvəl</option>
              <option value="date_added:asc">Ən köhnə əvvəl</option>
              <option value="price_azn:asc">Qiymət ↑</option>
              <option value="price_azn:desc">Qiymət ↓</option>
              <option value="year:desc">İl ↓</option>
              <option value="odometer:asc">Yürüş ↑</option>
              <option value="days_to_sell:asc">Satış günü ↑</option>
            </select>
          </div>
        )}
      </div>

      {/* Features section */}
      {featureOptions.length > 0 && (
        <div>
          <SectionHeader id="features" title={`Xüsusiyyətlər${selectedFeatureIds.length ? ` (${selectedFeatureIds.length})` : ""}`} />
          {openSection === "features" && (
            <div>
              <input
                type="text"
                placeholder="Xüsusiyyət axtar..."
                value={featureSearch}
                onChange={(e) => setFeatureSearch(e.target.value)}
                className="border rounded px-2 py-1.5 text-sm w-full mb-2"
              />
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-1 max-h-48 overflow-y-auto">
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

      {/* Reset button */}
      <div className="flex justify-end pt-1 border-t">
        <button
          onClick={() => onChange(defaultFilters)}
          className="border rounded px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 transition-colors"
        >
          Sıfırla
        </button>
      </div>
    </div>
  );
}
