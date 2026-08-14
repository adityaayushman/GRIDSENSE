import { useEffect, useState } from "react";
import {
  AreaChart, Area, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from "recharts";
import { ChevronDown, Zap, TrendingDown, Leaf, Battery, Euro, Github } from "lucide-react";
import { runScenario, fetchDays, warmUp, ScenarioResponse } from "./api";
import "./index.css";

type Objective = "emissions" | "cost" | "peak";

/** A reduction can be negative — optimizing one objective often worsens another
 *  on real grid data. Render that as an increase rather than a minus sign. */
function Delta({ pct }: { pct: number }) {
  const improved = pct >= 0;
  return (
    <span style={{ color: improved ? "#4FD1C5" : "#F2A65A" }}>
      {improved ? `${pct}%` : `+${Math.abs(pct)}%`}
    </span>
  );
}

export default function App() {
  const [evCount, setEvCount] = useState(80);
  const [chargerKw, setChargerKw] = useState(7);
  const [objective, setObjective] = useState<Objective>("emissions");
  const [methodOpen, setMethodOpen] = useState(false);
  const [result, setResult] = useState<ScenarioResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState<string[]>([]);
  const [day, setDay] = useState<string>("");

  useEffect(() => {
    warmUp();
    fetchDays()
      .then((d) => {
        setDays(d.days);
        setDay(d.default);
      })
      .catch(() => {
        /* day picker stays empty; the API then serves its own default */
      });
  }, []);

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
        region: "ES",
        ...(day ? { day } : {}),
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
            <div className="brandTag">carbon-aware charge scheduling · ES grid</div>
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
            <div className="field">
              <label>Grid night (measured)</label>
              <select className="daySelect" value={day} onChange={(e) => setDay(e.target.value)}>
                {days.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
              <div className="fieldValue">{days.length} nights of real ES data</div>
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
                value={<Delta pct={result.peak_reduction_pct} />}
                sub={`${result.peak_naive_kw} kW → ${result.peak_optimized_kw} kW`} />
              <StatCard icon={<Leaf size={18} color="#4FD1C5" />} label="Grid CO₂ reduction"
                value={<Delta pct={result.emissions_reduction_pct} />}
                sub={`${result.emissions_naive_kg} kg → ${result.emissions_optimized_kg} kg`} />
              <StatCard icon={<Euro size={18} color="#4FD1C5" />} label="Charging cost reduction"
                value={<Delta pct={result.cost_reduction_pct} />}
                sub={`€${result.cost_naive} → €${result.cost_optimized}`} />
              <StatCard icon={<Battery size={18} color="#4FD1C5" />} label="Energy scheduled"
                value={<>{result.energy_scheduled_kwh} kWh</>}
                sub={`${result.ev_count} vehicles · night of ${result.day}`} />
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
              <div className="eyebrow">AVERAGE GRID CARBON INTENSITY — 24H</div>
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
            <>
            <p className="methodText">
              Each vehicle's charge requirement is scheduled by a linear program minimizing the selected
              objective, subject to (1) total energy delivered by the deadline, (2) per-session power ≤ charger
              rating. Every curve shown is measured, not modelled: carbon intensity is derived from the
              ENTSO-E Spanish generation mix weighted by IPCC AR5 lifecycle emission factors, and price is the
              day-ahead market clearing price plus the flat PVPC access component. A night runs 18:00→07:00,
              so hours 00:00–07:00 on the chart are the following morning. This is <em>average</em> grid
              intensity, not marginal — the emissions of the average kWh rather than of the next one. Load
              shifting really responds to the marginal rate, which needs data this dataset does not carry.
            </p>
            <p className="methodText">
              The default night is the <em>median</em> night by achievable CO₂ saving — not the best one, and
              the picker offers a 46-night sample drawn to preserve the full year's distribution. Savings are
              long-tailed: across all 361 nights of 2018 the median is 3.3% and the fleet-wide total 10.4%,
              but 38% of nights save under 1% while 17% save over 20%. Objectives genuinely conflict — the
              cheapest hour and the cleanest hour coincide on only 14% of nights — so optimizing for cost can
              raise emissions, and optimizing for emissions can raise peak. Those are shown as increases
              rather than hidden.
            </p>
            </>
          )}
        </section>
      </main>

      <footer className="footer">
        <span>Data: ENTSO-E Spain 2018 (generation mix + day-ahead prices) · emission factors IPCC AR5</span>
        <a href="https://github.com/adityaasahoo/gridsense" className="footerLink"
           target="_blank" rel="noreferrer"><Github size={14} /> Source</a>
      </footer>
    </div>
  );
}

function StatCard({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: React.ReactNode; sub: string }) {
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
