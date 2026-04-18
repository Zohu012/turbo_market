import { Routes, Route, NavLink, Outlet, useNavigate } from "react-router-dom";
import DealerTool from "./pages/DealerTool";
import Analytics from "./pages/Analytics";
import AdminDashboard from "./pages/AdminDashboard";
import SellerProfile from "./pages/SellerProfile";
import VehicleDetail from "./pages/VehicleDetail";
import Login from "./pages/Login";
import PrivateRoute from "./components/PrivateRoute";

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
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/admin" element={<AdminDashboard />} />
          <Route path="/sellers/:id" element={<SellerProfile />} />
          <Route path="/vehicles/:turboId" element={<VehicleDetail />} />
        </Route>
      </Route>
    </Routes>
  );
}
