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
 *
 * The dev host is `127.0.0.1`, not `localhost`, on purpose. Windows resolves
 * `localhost` to `::1` first, while `uvicorn --reload` binds IPv4 only, so the
 * browser opens a connection to an address nothing is listening on and every
 * request fails with a network error that reads exactly like a CORS problem.
 * Naming the IPv4 address removes the ambiguity.
 */
const API_BASE =
  import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? "http://127.0.0.1:8000" : "");

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
  /** Which grid to schedule against; defaults to 2018 server-side. */
  era?: Era;
  /** Shared transformer limit in kW. Omit for an unconstrained feeder. */
  feeder_capacity_kw?: number;
  /** Schedule against the day-ahead forecast instead of the measured curve. */
  use_forecast?: boolean;
  /**
   * Forecast gate: charge on arrival unless the forecast expects at least this
   * many percent saving. Only meaningful with `use_forecast`.
   */
  gate_min_saving_pct?: number;
  /** A mixed fleet as groups of identical vehicles; replaces the single-group fields. */
  fleet?: FleetGroup[];
  /** Let vehicles discharge back to the grid. */
  allow_v2g?: boolean;
}

export interface FleetGroup {
  count: number;
  energy_per_vehicle_kwh: number;
  charger_kw: number;
  arrival_hour?: number;
  deadline_hour?: number;
}

/**
 * India's fleet, by FADA calendar-2025 registrations: 56% two-wheelers, 35%
 * three-wheelers, 8% cars. Energy and charger ratings mirror ml/india_fleet.py.
 */
const INDIAN_SEGMENTS = [
  { share: 0.564, energy: 1.8, charger: 0.9 },   // e-2W
  { share: 0.351, energy: 6.5, charger: 1.9 },   // e-3W
  { share: 0.085, energy: 9.2, charger: 3.3 },   // e-car (remainder, so the total is exact)
];

/** `n` vehicles in the national mix, by largest-remainder allocation. */
export function indianFleet(n: number): FleetGroup[] {
  const exact = INDIAN_SEGMENTS.map((s) => n * s.share);
  const counts = exact.map(Math.floor);
  let left = n - counts.reduce((a, b) => a + b, 0);
  [...exact.keys()]
    .sort((a, b) => (exact[b] - counts[b]) - (exact[a] - counts[a]))
    .forEach((i) => { if (left > 0) { counts[i] += 1; left -= 1; } });
  return INDIAN_SEGMENTS
    .map((s, i) => ({ count: counts[i], energy_per_vehicle_kwh: s.energy, charger_kw: s.charger }))
    .filter((g) => g.count > 0);
}

export interface HourlyPoint {
  hour: number;
  label: string;
  naive_kw: number;
  optimized_kw: number;
  carbon_intensity: number;
  price: number;
}

export type Era = "2018" | "2025";

export interface YearStats {
  year: number;
  nights: number;
  median_saving_pct: number;
  total_saving_pct: number;
  under_1pct: number;
  over_20pct: number;
}

export interface DaysResponse {
  days: string[];
  default: string;
  count: number;
  region: string;
  era: Era;
  eras: Era[];
  year_stats: YearStats | null;
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
  used_forecast: boolean;
  used_v2g: boolean;
  exported_kwh: number;
  forecast_available: boolean;
  hourly_forecast: number[] | null;
  gate_applied: boolean;
  /** False when the gate stepped aside and the fleet charged on arrival. */
  gate_acted: boolean;
  gate_expected_saving_pct: number | null;
  gate_reason: string | null;
  run_id: number | null;
  era: Era;
}

/** The threshold finding 13 settled on: the out-of-sample optimum on the corrected 2018 record, and free on 2025. */
export const GATE_MIN_SAVING_PCT = 4;

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

export async function fetchDays(era: Era = "2018"): Promise<DaysResponse> {
  const res = await fetch(`${API_BASE}/api/days?era=${era}`);
  if (!res.ok) throw new Error(`Could not load available days (${res.status})`);
  return res.json();
}

/** Why a request failed, in terms a visitor can act on. */
export class ApiError extends Error {
  constructor(
    message: string,
    /** "unreachable": no response (offline, cold start, blocked); "rejected": the API said no; "server": it broke. */
    public kind: "unreachable" | "rejected" | "server",
    public status?: number,
  ) {
    super(message);
  }
}

/** The API's own explanation, when it gave one (FastAPI puts it in `detail`). */
function detailOf(body: string): string {
  try {
    const d = JSON.parse(body)?.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => x?.msg ?? String(x)).join("; ");
  } catch { /* not JSON */ }
  return body.slice(0, 200);
}

export async function runScenario(req: ScenarioRequest): Promise<ScenarioResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/scenario`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
  } catch {
    throw new ApiError("The scheduling API did not respond.", "unreachable");
  }
  if (!res.ok) {
    const detail = detailOf(await res.text());
    // 404 and 405 mean nothing answers at this address (no API route), which is a reachability
    // problem to the visitor. Only a 4xx with the API's own explanation is a rejected scenario.
    if (res.status === 404 || res.status === 405) {
      throw new ApiError("The scheduling API is not available at this address.", "unreachable", res.status);
    }
    throw new ApiError(detail || `Request failed (${res.status})`, res.status >= 500 ? "server" : "rejected", res.status);
  }
  return res.json();
}

export interface RunRow {
  id: number;
  created_at: string;
  day: string | null;
  objective: string | null;
  ev_count: number | null;
  emissions_reduction_pct: number | null;
  cost_reduction_pct: number | null;
  peak_reduction_pct: number | null;
}

/** Recent recorded runs, or [] when the API has no database behind it (it answers 501). */
export async function fetchRuns(limit = 10): Promise<RunRow[]> {
  try {
    const res = await fetch(`${API_BASE}/api/runs?limit=${limit}`);
    if (!res.ok) return [];
    return (await res.json()).runs ?? [];
  } catch {
    return [];
  }
}

export interface IndiaLiveDay {
  /** False when the portal could not be reached and a stored day is shown instead. */
  live: boolean;
  live_error?: string;
  day: string;
  age_days: number;
  fresh: boolean;
  mean_carbon_intensity: number;
  cleanest_hour: number;
  dirtiest_hour: number;
  hourly: { hour: number; label: string; carbon_intensity: number; demand_met_mw: number; renewable_share_pct: number }[];
  checks: { solar_zero_at_night: boolean; fuels_sum_to_total: boolean; median_closure_gap_pct: number | null; plausible: boolean };
  source: string;
  note: string;
}

/** Newest Indian grid day from Grid-India via the API. Needs no key. */
export async function fetchIndiaLive(): Promise<IndiaLiveDay> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/india/live`);
  } catch {
    throw new Error("the API did not respond");
  }
  // A host with no API behind it answers with its HTML page; say so in words, not a parse error.
  const isJson = (res.headers.get("content-type") ?? "").includes("json");
  if (!res.ok || !isJson) {
    let why = res.ok ? "the API is not available at this address" : `HTTP ${res.status}`;
    if (isJson) {
      try { why = (await res.json()).detail ?? why; } catch { /* keep the status */ }
    }
    throw new Error(why);
  }
  return res.json();
}
