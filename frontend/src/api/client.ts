import axios from "axios";

const api = axios.create({
  baseURL: "/api/v1",
  headers: { "Content-Type": "application/json" },
});

// Attach JWT token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) config.headers["Authorization"] = `Bearer ${token}`;
  return config;
});

// On 401, clear token and redirect to login
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("token");
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

export default api;

// ── Types ────────────────────────────────────────────────────────────────────

export interface VehicleImage {
  id: number;
  url: string;
  position: number;
  is_primary: boolean;
}

export interface PriceHistoryPoint {
  id: number;
  price: number;
  currency: string;
  price_azn: number | null;
  recorded_at: string;
}

export interface SellerBrief {
  id: number;
  name: string | null;
  seller_type: string | null;
  city: string | null;
  total_listings: number;
  total_sold: number;
}

export interface Vehicle {
  id: number;
  turbo_id: number;
  make: string;
  model: string;
  year: number | null;
  price: number | null;
  currency: string | null;
  price_azn: number | null;
  odometer: number | null;
  odometer_type: string | null;
  color: string | null;
  engine: string | null;
  fuel_type: string | null;
  transmission: string | null;
  body_type: string | null;
  city: string | null;
  status: string;
  date_added: string;
  date_updated: string;
  date_deactivated: string | null;
  days_to_sell: number | null;
  url: string;
  primary_image: string | null;
  images?: VehicleImage[];
  price_history?: PriceHistoryPoint[];
  seller?: SellerBrief | null;
}

export interface PagedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pages: number;
}

export interface OverviewStats {
  total_active: number;
  total_inactive: number;
  new_today: number;
  sold_today: number;
  avg_days_to_sell: number | null;
  total_vehicles: number;
}

export interface PriceStats {
  avg: number | null;
  min: number | null;
  max: number | null;
  median: number | null;
  count: number;
}

export interface TrendPoint {
  period: string;
  avg_price: number | null;
  median_price: number | null;
  count: number;
}

export interface BestSeller {
  make: string;
  model: string;
  total_sold: number;
  avg_days_to_sell: number | null;
  avg_price_azn: number | null;
}

export interface InventoryByMake {
  make: string;
  active_count: number;
  inactive_count: number;
  avg_price_azn: number | null;
}

export interface ScrapeJob {
  id: number;
  job_type: string;
  status: string;
  triggered_by: string;
  target_make: string | null;
  target_model: string | null;
  celery_task_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  listings_found: number;
  listings_new: number;
  listings_updated: number;
  listings_deactivated: number;
  error_message: string | null;
  created_at: string;
}

// ── API calls ────────────────────────────────────────────────────────────────

export const vehiclesApi = {
  list: (params: Record<string, unknown>) =>
    api.get<PagedResponse<Vehicle>>("/vehicles", { params }),
  get: (turboId: number) => api.get<Vehicle>(`/vehicles/${turboId}`),
  makes: () => api.get<{ makes: string[] }>("/vehicles/makes"),
  models: (make: string) => api.get<{ models: string[] }>("/vehicles/models", { params: { make } }),
};

export const analyticsApi = {
  overview: () => api.get<OverviewStats>("/analytics/overview"),
  prices: (params?: Record<string, unknown>) => api.get<PriceStats>("/analytics/prices", { params }),
  priceTrend: (params?: Record<string, unknown>) =>
    api.get<TrendPoint[]>("/analytics/price-trend", { params }),
  bestSellers: (params?: Record<string, unknown>) =>
    api.get<BestSeller[]>("/analytics/best-sellers", { params }),
  daysToSell: (params?: Record<string, unknown>) =>
    api.get("/analytics/days-to-sell", { params }),
  inventoryByMake: () => api.get<InventoryByMake[]>("/analytics/inventory-by-make"),
};

export const sellersApi = {
  list: (params?: Record<string, unknown>) => api.get("/sellers", { params }),
  get: (id: number) => api.get(`/sellers/${id}`),
  vehicles: (id: number, params?: Record<string, unknown>) =>
    api.get(`/sellers/${id}/vehicles`, { params }),
};

export const adminApi = {
  trigger: (body: { job_type: string; target_make?: string; target_model?: string }) =>
    api.post<ScrapeJob>("/admin/scrape/trigger", body),
  jobs: (params?: Record<string, unknown>) =>
    api.get<PagedResponse<ScrapeJob>>("/admin/scrape/jobs", { params }),
  job: (id: number) => api.get<ScrapeJob>(`/admin/scrape/jobs/${id}`),
  stats: () => api.get("/admin/stats"),
};
