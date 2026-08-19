/**
 * Where the API lives.
 *
 * In production the API is served from the same origin as this page (Vercel
 * routes /api/* to the Python function), so the base is empty and requests go
 * to a relative /api/... — no CORS, and no build-time coupling to a hostname.
 * In dev the backend is a separate uvicorn on :8000. VITE_API_BASE still
 * overrides both, for a split deployment such as the backend on Render.
 *
 * Note `??` rather than `||`: an intentionally empty VITE_API_BASE means
 * same-origin, and `||` would discard it in favour of localhost.
 */
const API_BASE =
  import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? "http://localhost:8000" : "");

export interface ScenarioRequest {
  ev_count: number;
  charger_kw: number;
  arrival_hour: number;
  deadline_hour: number;
  energy_per_vehicle_kwh: number;
  objective: "emissions" | "cost" | "peak";
  region: string;
  /** ISO date of the measured charging night; omit for the representative default. */
  day?: string;
  /** Shared transformer limit in kW. Omit for an unconstrained feeder. */
  feeder_capacity_kw?: number;
}

export interface HourlyPoint {
  hour: number;
  label: string;
  naive_kw: number;
  optimized_kw: number;
  carbon_intensity: number;
  price: number;
}

export interface DaysResponse {
  days: string[];
  default: string;
  count: number;
  region: string;
}

export interface ScenarioResponse {
  hourly: HourlyPoint[];
  peak_naive_kw: number;
  peak_optimized_kw: number;
  peak_reduction_pct: number;
  emissions_naive_kg: number;
  emissions_optimized_kg: number;
  emissions_reduction_pct: number;
  cost_naive: number;
  cost_optimized: number;
  cost_reduction_pct: number;
  currency: string;
  energy_scheduled_kwh: number;
  ev_count: number;
  region: string;
  day: string;
  feeder_capacity_kw: number | null;
  naive_overload_hours: number;
  naive_overload_peak_kw: number;
}

/**
 * Fire-and-forget ping to warm the API before the first real request.
 *
 * The API is a serverless function, so an idle deployment pays a cold start on
 * its next invocation (~1-2s on Vercel; ~50s if hosted on a Render free-tier
 * container, which spins down after ~15 minutes). Calling this on mount moves
 * that cost into the window where the visitor is still reading the page.
 */
export function warmUp(): void {
  fetch(`${API_BASE}/api/health`).catch(() => {
    /* best-effort only; a failure here is surfaced on the real request */
  });
}

export async function fetchDays(): Promise<DaysResponse> {
  const res = await fetch(`${API_BASE}/api/days`);
  if (!res.ok) throw new Error(`Could not load available days (${res.status})`);
  return res.json();
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
