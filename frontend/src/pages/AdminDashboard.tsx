import { useEffect, useState } from "react";
import { adminApi, type ScrapeJob, type PagedResponse } from "../api/client";
import JobStatusBadge from "../components/JobStatusBadge";

export default function AdminDashboard() {
  const [jobs, setJobs] = useState<PagedResponse<ScrapeJob> | null>(null);
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const [triggerMake, setTriggerMake] = useState("");
  const [triggerModel, setTriggerModel] = useState("");
  const [jobType, setJobType] = useState("make_scan");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const loadData = async () => {
    try {
      const [jobsRes, statsRes] = await Promise.all([
        adminApi.jobs({ page_size: 20 }),
        adminApi.stats(),
      ]);
      setJobs(jobsRes.data);
      setStats(statsRes.data as Record<string, unknown>);
      setError("");
    } catch {
      setError("Failed to load data");
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const trigger = async () => {
    setSubmitting(true);
    try {
      await adminApi.trigger({
        job_type: jobType,
        target_make: triggerMake || undefined,
        target_model: triggerModel || undefined,
      });
      await loadData();
    } catch {
      setError("Trigger failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Admin Dashboard</h1>

      {error && <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-2 rounded text-sm">{error}</div>}

      {/* DB Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-white border rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase">Active Vehicles</p>
            <p className="text-2xl font-bold text-blue-600">{(stats.active_vehicles as number)?.toLocaleString()}</p>
          </div>
          <div className="bg-white border rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase">Total in DB</p>
            <p className="text-2xl font-bold">{(stats.total_vehicles as number)?.toLocaleString()}</p>
          </div>
          <div className="bg-white border rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase">DB Size</p>
            <p className="text-2xl font-bold text-purple-600">{stats.db_size as string}</p>
          </div>
          <div className="bg-white border rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase">Last Full Scan</p>
            <p className="text-sm font-medium mt-2">
              {stats.last_full_scan ? (stats.last_full_scan as string).slice(0, 16).replace("T", " ") : "Never"}
            </p>
          </div>
        </div>
      )}

      {/* Trigger scan */}
      <div className="bg-white rounded-lg border p-4">
        <h2 className="font-semibold mb-3">Trigger Scrape</h2>
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="text-xs text-gray-500 block mb-1">Job Type</label>
            <select
              value={jobType}
              onChange={(e) => setJobType(e.target.value)}
              className="border rounded px-2 py-1.5 text-sm"
            >
              <optgroup label="Standard">
                <option value="make_scan">Make Scan</option>
                <option value="full_scan">Full Scan (all makes)</option>
                <option value="lifecycle_check">Lifecycle Check only</option>
              </optgroup>
              <optgroup label="Parallel — fast (8 workers)">
                <option value="listing_parallel">Listing (Parallel)</option>
                <option value="details_full_parallel">Details Full (Parallel)</option>
                <option value="details_update_parallel">Details Update (Parallel)</option>
              </optgroup>
            </select>
          </div>
          {(jobType === "make_scan" ||
            jobType === "listing_parallel" ||
            jobType === "details_full_parallel") && (
            <>
              <div>
                <label className="text-xs text-gray-500 block mb-1">
                  Make {jobType !== "make_scan" && "(optional)"}
                </label>
                <input
                  className="border rounded px-2 py-1.5 text-sm"
                  placeholder="e.g. Toyota"
                  value={triggerMake}
                  onChange={(e) => setTriggerMake(e.target.value)}
                />
              </div>
              {jobType === "make_scan" && (
                <div>
                  <label className="text-xs text-gray-500 block mb-1">Model (optional)</label>
                  <input
                    className="border rounded px-2 py-1.5 text-sm"
                    placeholder="e.g. Camry"
                    value={triggerModel}
                    onChange={(e) => setTriggerModel(e.target.value)}
                  />
                </div>
              )}
            </>
          )}
          <button
            onClick={trigger}
            disabled={submitting || (jobType === "make_scan" && !triggerMake)}
            className="px-4 py-1.5 bg-green-600 text-white rounded text-sm hover:bg-green-700 disabled:opacity-40"
          >
            {submitting ? "Triggering..." : "▶ Run Now"}
          </button>
          {jobType.endsWith("_parallel") && (
            <span className="text-xs text-purple-600 bg-purple-50 px-2 py-1 rounded font-medium">
              ⚡ Parallel — 8 workers
            </span>
          )}
          <button onClick={loadData} className="px-3 py-1.5 border rounded text-sm hover:bg-gray-50">
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Job history */}
      <div className="bg-white rounded-lg border">
        <div className="px-4 py-3 border-b">
          <h2 className="font-semibold">Recent Scrape Jobs</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                {["ID", "Type", "Status", "Triggered by", "Target", "Found", "New", "Updated", "Deactivated", "Started", "Duration"].map((h) => (
                  <th key={h} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {jobs?.items.map((j) => {
                const duration = j.started_at && j.finished_at
                  ? Math.round((new Date(j.finished_at).getTime() - new Date(j.started_at).getTime()) / 1000)
                  : null;
                return (
                  <tr key={j.id} className="hover:bg-gray-50">
                    <td className="px-3 py-2 text-gray-400">{j.id}</td>
                    <td className="px-3 py-2 font-medium">{j.job_type}</td>
                    <td className="px-3 py-2"><JobStatusBadge status={j.status} /></td>
                    <td className="px-3 py-2">{j.triggered_by}</td>
                    <td className="px-3 py-2">{j.target_make ?? "all"}{j.target_model ? ` / ${j.target_model}` : ""}</td>
                    <td className="px-3 py-2 text-right">{j.listings_found.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right text-green-600">{j.listings_new.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right text-blue-600">{j.listings_updated.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right text-orange-500">{j.listings_deactivated.toLocaleString()}</td>
                    <td className="px-3 py-2 text-gray-500">{j.started_at?.slice(0, 16).replace("T", " ") ?? "—"}</td>
                    <td className="px-3 py-2">{duration ? `${duration}s` : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
