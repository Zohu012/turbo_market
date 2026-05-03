import { NavLink } from "react-router-dom";
import { AZ } from "../../i18n/az";

interface NavItem {
  label: string;
  to: string;
  active: boolean;
}

const NAV: NavItem[] = [
  // Bazar baxışı
  { label: AZ.dashboards.overview, to: "/analytics", active: true },
  // Qiymət
  { label: AZ.dashboards.price, to: "/analytics/price", active: true },
  { label: AZ.dashboards.priceDrops, to: "/analytics/price-drops", active: true },
  { label: AZ.dashboards.discounts, to: "/analytics/discounts", active: true },
  // Likvidlik
  { label: AZ.dashboards.dts, to: "/analytics/dts", active: true },
  { label: AZ.dashboards.ageing, to: "/analytics/ageing", active: true },
  // Marka & Model
  { label: AZ.dashboards.makemodel, to: "/analytics/vehicle", active: true },
  { label: AZ.dashboards.liquidity, to: "/analytics/liquidity", active: true },
  { label: AZ.dashboards.features, to: "/analytics/features", active: true },
  { label: AZ.dashboards.condition, to: "/analytics/condition", active: true },
  { label: AZ.dashboards.trends, to: "/analytics/trends", active: true },
  { label: AZ.dashboards.cities, to: "/analytics/cities", active: true },
  // Satıcılar
  { label: AZ.dashboards.competitors, to: "/analytics/competitors", active: true },
  { label: AZ.dashboards.pricing, to: "/analytics/pricing", active: true },
  { label: AZ.dashboards.opportunities, to: "/analytics/opportunities", active: true },
  { label: "Hesabat ixracı", to: "/analytics/export", active: false },
];

const GROUPS = [
  { label: AZ.groups.bazarBaxisi, items: NAV.slice(0, 1) },
  { label: AZ.groups.qiymet, items: NAV.slice(1, 4) },
  { label: AZ.groups.likvidlik, items: NAV.slice(4, 6) },
  { label: AZ.groups.markaModel, items: NAV.slice(6, 12) },
  { label: AZ.groups.saticılar, items: NAV.slice(12) },
];

const navClass = (active: boolean, isActive: boolean) =>
  `block px-3 py-1.5 rounded text-sm transition-colors ${
    !active
      ? "text-gray-300 cursor-not-allowed"
      : isActive
      ? "bg-blue-600 text-white font-medium"
      : "text-gray-700 hover:bg-gray-100"
  }`;

export default function AnalyticsSidebar() {
  return (
    <aside className="w-52 shrink-0 flex flex-col gap-4 py-2">
      {GROUPS.map((group) => (
        <div key={group.label}>
          <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide px-3 mb-1">
            {group.label}
          </div>
          <ul className="space-y-0.5">
            {group.items.map((item) => (
              <li key={item.to}>
                {item.active ? (
                  <NavLink
                    to={item.to}
                    end={item.to === "/analytics"}
                    className={({ isActive }) => navClass(true, isActive)}
                  >
                    {item.label}
                  </NavLink>
                ) : (
                  <span className={navClass(false, false)}>
                    {item.label}
                    <span className="ml-1 text-xs bg-gray-100 text-gray-400 rounded px-1 py-0.5">
                      {AZ.dashboards.comingSoon}
                    </span>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </aside>
  );
}
