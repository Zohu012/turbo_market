import { Routes, Route, NavLink, Outlet, useNavigate } from "react-router-dom";
import DealerTool from "./pages/DealerTool";
import AdminDashboard from "./pages/AdminDashboard";
import SellerProfile from "./pages/SellerProfile";
import VehicleDetail from "./pages/VehicleDetail";
import Login from "./pages/Login";
import PrivateRoute from "./components/PrivateRoute";
import AnalyticsLayout from "./components/analytics/AnalyticsLayout";
import OverviewDashboard from "./pages/analytics/OverviewDashboard";
import MarketPriceDashboard from "./pages/analytics/MarketPriceDashboard";
import DaysToSellDashboard from "./pages/analytics/DaysToSellDashboard";
import MakeModelDashboard from "./pages/analytics/MakeModelDashboard";
import PriceDropsDashboard from "./pages/analytics/PriceDropsDashboard";
import AgeingDashboard from "./pages/analytics/AgeingDashboard";
import LiquidityDashboard from "./pages/analytics/LiquidityDashboard";
import FeaturesDashboard from "./pages/analytics/FeaturesDashboard";
import ConditionDashboard from "./pages/analytics/ConditionDashboard";
import TrendsDashboard from "./pages/analytics/TrendsDashboard";
import CitiesDashboard from "./pages/analytics/CitiesDashboard";
import CompetitorsDashboard from "./pages/analytics/CompetitorsDashboard";
import PricingDashboard from "./pages/analytics/PricingDashboard";
import OpportunitiesDashboard from "./pages/analytics/OpportunitiesDashboard";
import ComingSoon from "./pages/analytics/ComingSoon";

const navClass = ({ isActive }: { isActive: boolean }) =>
  `px-4 py-2 rounded-md text-sm font-medium transition-colors ${
    isActive
      ? "bg-blue-600 text-white"
      : "text-gray-600 hover:bg-gray-100"
  }`;

function Layout() {
  const navigate = useNavigate();
  const logout = () => {
    localStorage.removeItem("token");
    navigate("/login", { replace: true });
  };
  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white border-b shadow-sm sticky top-0 z-10">
        <div className="max-w-screen-2xl mx-auto px-4 py-3 flex items-center gap-6">
          <span className="text-xl font-bold text-blue-600">TurboMarket</span>
          <nav className="flex gap-2 flex-1">
            <NavLink to="/" className={navClass} end>Vehicles</NavLink>
            <NavLink to="/analytics" className={navClass}>Analytics</NavLink>
            <NavLink to="/admin" className={navClass}>Admin</NavLink>
          </nav>
          <button
            onClick={logout}
            className="text-sm text-gray-500 hover:text-gray-800 px-3 py-1.5 rounded border hover:border-gray-400 transition-colors"
          >
            Sign out
          </button>
        </div>
      </header>
      <main className="flex-1 max-w-screen-2xl mx-auto w-full px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<PrivateRoute />}>
        <Route element={<Layout />}>
          <Route path="/" element={<DealerTool />} />

          {/* Analytics — nested routes under shared layout with global filters */}
          <Route path="/analytics" element={<AnalyticsLayout />}>
            <Route index element={<OverviewDashboard />} />
            <Route path="price" element={<MarketPriceDashboard />} />
            <Route path="dts" element={<DaysToSellDashboard />} />
            <Route path="vehicle" element={<MakeModelDashboard />} />
            <Route path="price-drops" element={<PriceDropsDashboard />} />
            <Route path="discounts" element={<PriceDropsDashboard />} />
            <Route path="ageing" element={<AgeingDashboard />} />
            <Route path="liquidity" element={<LiquidityDashboard />} />
            <Route path="features" element={<FeaturesDashboard />} />
            <Route path="condition" element={<ConditionDashboard />} />
            <Route path="trends" element={<TrendsDashboard />} />
            <Route path="cities" element={<CitiesDashboard />} />
            <Route path="competitors" element={<CompetitorsDashboard />} />
            <Route path="pricing" element={<PricingDashboard />} />
            <Route path="opportunities" element={<OpportunitiesDashboard />} />
            {/* Catch-all for future dashboards */}
            <Route path=":slug" element={<ComingSoon />} />
          </Route>

          <Route path="/admin" element={<AdminDashboard />} />
          <Route path="/sellers/:id" element={<SellerProfile />} />
          <Route path="/vehicles/:turboId" element={<VehicleDetail />} />
        </Route>
      </Route>
    </Routes>
  );
}
