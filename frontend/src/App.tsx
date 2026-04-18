import { Routes, Route, NavLink } from "react-router-dom";
import DealerTool from "./pages/DealerTool";
import Analytics from "./pages/Analytics";
import AdminDashboard from "./pages/AdminDashboard";
import SellerProfile from "./pages/SellerProfile";
import VehicleDetail from "./pages/VehicleDetail";

const navClass = ({ isActive }: { isActive: boolean }) =>
  `px-4 py-2 rounded-md text-sm font-medium transition-colors ${
    isActive
      ? "bg-blue-600 text-white"
      : "text-gray-600 hover:bg-gray-100"
  }`;

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white border-b shadow-sm sticky top-0 z-10">
        <div className="max-w-screen-2xl mx-auto px-4 py-3 flex items-center gap-6">
          <span className="text-xl font-bold text-blue-600">TurboMarket</span>
          <nav className="flex gap-2">
            <NavLink to="/" className={navClass} end>Vehicles</NavLink>
            <NavLink to="/analytics" className={navClass}>Analytics</NavLink>
            <NavLink to="/admin" className={navClass}>Admin</NavLink>
          </nav>
        </div>
      </header>
      <main className="flex-1 max-w-screen-2xl mx-auto w-full px-4 py-6">
        <Routes>
          <Route path="/" element={<DealerTool />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/admin" element={<AdminDashboard />} />
          <Route path="/sellers/:id" element={<SellerProfile />} />
          <Route path="/vehicles/:turboId" element={<VehicleDetail />} />
        </Routes>
      </main>
    </div>
  );
}
