import { useEffect, useState } from "react";
import {
  AreaChart, Area, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from "recharts";
import { ChevronDown, Zap, TrendingDown, Leaf, Battery, DollarSign, Github } from "lucide-react";
import { runScenario, warmUp, ScenarioResponse } from "./api";
import "./index.css";

type Objective = "emissions" | "cost" | "peak";

export default function App() {
  const [evCount, setEvCount] = useState(80);
  const [chargerKw, setChargerKw] = useState(7);
  const [objective, setObjective] = useState<Objective>("emissions");
  const [methodOpen, setMethodOpen] = useState(false);
  const [result, setResult] = useState<ScenarioResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Start the API container waking as soon as the page loads — see warmUp().
  useEffect(warmUp, []);

  async function handleRun() {
    setLoading(true);
    setError(null);
    try {
      const res = await runScenario({
        ev_count: evCount,
        charger_kw: chargerKw,
        arrival_hour: 18,
        deadline_hour: 7,
        energy_per_vehicle_kwh: 9.2,
        objective,
        region: "CAISO",
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <div className="gridOverlay" />

      <header className="header">
        <div className="brand">
          <div className="brandMark"><Zap size={16} color="#0B0F14" strokeWidth={2.5} /></div>
          <div>
            <div className="brandName">GridSense</div>
            <div className="brandTag">carbon-aware charge scheduling</div>
          </div>
        </div>
        <div className="objectiveToggle">
          {(["emissions", "cost", "peak"] as Objective[]).map((key) => (
            <button
              key={key}
              onClick={() => setObjective(key)}
              className={`objectiveBtn ${objective === key ? "active" : ""}`}
            >
              {key === "emissions" ? "Min. Emissions" : key === "cost" ? "Min. Cost" : "Min. Peak Load"}
            </button>
          ))}
        </div>
      </header>

      <main className="main">
        <section className="card">
          <div className="eyebrow">SCENARIO</div>
          <div className="scenarioGrid">
            <div className="field">
              <label>EVs in neighborhood</label>
              <input type="range" min={10} max={200} value={evCount} onChange={(e) => setEvCount(+e.target.value)} />
              <div className="fieldValue">{evCount} vehicles</div>
            </div>
            <div className="field">
              <label>Charger rating</label>
              <input type="range" min={1.4} max={11} step={0.1} value={chargerKw} onChange={(e) => setChargerKw(+e.target.value)} />
              <div className="fieldValue">{chargerKw.toFixed(1)} kW</div>
            </div>
            <button className="runBtn" onClick={handleRun} disabled={loading}>
              {loading ? "Running…" : "Run simulation"}
            </button>
          </div>
          {error && <div className="errorText">{error}</div>}
        </section>

        {result && (
          <>
            <section className="statsGrid">
              <StatCard icon={<TrendingDown size={18} color="#4FD1C5" />} label="Peak load reduction"
                value={`${result.peak_reduction_pct}%`}
                sub={`${result.peak_naive_kw} kW → ${result.peak_optimized_kw} kW`} />
              <StatCard icon={<Leaf size={18} color="#4FD1C5" />} label="Marginal CO₂ reduction"
                value={`${result.emissions_reduction_pct}%`}
                sub={`${result.emissions_naive_kg} kg → ${result.emissions_optimized_kg} kg`} />
              <StatCard icon={<DollarSign size={18} color="#4FD1C5" />} label="Charging cost reduction"
                value={`${result.cost_reduction_pct}%`}
                sub={`$${result.cost_naive_usd} → $${result.cost_optimized_usd}`} />
              <StatCard icon={<Battery size={18} color="#4FD1C5" />} label="Energy scheduled"
                value={`${result.energy_scheduled_kwh} kWh`}
                sub={`${result.ev_count} vehicles · ${result.region}`} />
            </section>

            <section className="card">
              <div className="chartHeader">
                <div className="eyebrow">GRID LOAD — 24H</div>
                <Legend payload={[
                  { value: "Naive charging", type: "line", color: "#F2A65A" },
                  { value: "Optimized charging", type: "line", color: "#4FD1C5" },
                ]} />
              </div>
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart data={result.hourly} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="2 6" stroke="#232B36" vertical={false} />
                  <XAxis dataKey="label" interval={2} tick={{ fill: "#8B96A5", fontSize: 11 }} axisLine={{ stroke: "#232B36" }} tickLine={false} />
                  <YAxis tick={{ fill: "#8B96A5", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ background: "#0B0F14", border: "1px solid #232B36" }} />
                  <Area type="monotone" dataKey="naive_kw" stroke="#F2A65A" fill="#F2A65A" fillOpacity={0.08} strokeWidth={2} />
                  <Area type="monotone" dataKey="optimized_kw" stroke="#4FD1C5" fill="#4FD1C5" fillOpacity={0.12} strokeWidth={2.5} />
                </AreaChart>
              </ResponsiveContainer>
            </section>

            <section className="card">
              <div className="eyebrow">MARGINAL CARBON INTENSITY — 24H</div>
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={result.hourly} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="2 6" stroke="#232B36" vertical={false} />
                  <XAxis dataKey="label" interval={2} tick={{ fill: "#8B96A5", fontSize: 11 }} axisLine={{ stroke: "#232B36" }} tickLine={false} />
                  <YAxis tick={{ fill: "#8B96A5", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ background: "#0B0F14", border: "1px solid #232B36" }} />
                  <Line type="monotone" dataKey="carbon_intensity" stroke="#F2A65A" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </section>
          </>
        )}

        {!result && !loading && (
          <div className="emptyState">Set your scenario above and run a simulation to see results.</div>
        )}

        <section className="card">
          <button className="methodToggle" onClick={() => setMethodOpen(!methodOpen)}>
            <span className="eyebrow">METHODOLOGY</span>
            <ChevronDown size={16} color="#8B96A5" style={{ transform: methodOpen ? "rotate(180deg)" : "none" }} />
          </button>
          {methodOpen && (
            <p className="methodText">
              Each vehicle's charge requirement is scheduled by a linear program minimizing the selected
              objective, subject to (1) total energy delivered by the deadline, (2) per-session power ≤ charger
              rating. Marginal emissions data sourced from WattTime; time-of-use pricing modeled on PG&amp;E's
              EV2-A residential EV tariff; charging session distributions modeled on ACN-Data (Caltech).
            </p>
          )}
        </section>
      </main>

      <footer className="footer">
        <span>Data: WattTime · ElectricityMaps · ACN-Data (Caltech)</span>
        <a href="#" className="footerLink"><Github size={14} /> Source</a>
      </footer>
    </div>
  );
}

function StatCard({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub: string }) {
  return (
    <div className="statCard">
      <div>{icon}</div>
      <div>
        <div className="statLabel">{label}</div>
        <div className="statValue">{value}</div>
        <div className="statSub">{sub}</div>
      </div>
    </div>
  );
}
