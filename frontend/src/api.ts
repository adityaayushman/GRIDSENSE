const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export interface ScenarioRequest {
  ev_count: number;
  charger_kw: number;
  arrival_hour: number;
  deadline_hour: number;
  energy_per_vehicle_kwh: number;
  objective: "emissions" | "cost" | "peak";
  region: string;
}

export interface HourlyPoint {
  hour: number;
  label: string;
  naive_kw: number;
  optimized_kw: number;
  carbon_intensity: number;
}

export interface ScenarioResponse {
  hourly: HourlyPoint[];
  peak_naive_kw: number;
  peak_optimized_kw: number;
  peak_reduction_pct: number;
  emissions_naive_kg: number;
  emissions_optimized_kg: number;
  emissions_reduction_pct: number;
  cost_naive_usd: number;
  cost_optimized_usd: number;
  cost_reduction_pct: number;
  energy_scheduled_kwh: number;
  ev_count: number;
  region: string;
}

/**
 * Fire-and-forget ping to start the API container booting.
 *
 * Render's free tier spins a service down after ~15 minutes idle, and a cold
 * boot costs roughly 50s. Calling this on mount means the container is waking
 * while the visitor is still reading the page, rather than after they hit Run.
 */
export function warmUp(): void {
  fetch(`${API_BASE}/api/health`).catch(() => {
    /* best-effort only; a failure here is surfaced on the real request */
  });
}

export async function runScenario(req: ScenarioRequest): Promise<ScenarioResponse> {
  const res = await fetch(`${API_BASE}/api/scenario`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Scenario request failed (${res.status}): ${detail}`);
  }
  return res.json();
}
