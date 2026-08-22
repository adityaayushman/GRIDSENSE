import { useCallback, useEffect, useRef, useState } from "react";
import {
  AreaChart, Area, LineChart, Line, ReferenceLine,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { ChevronDown, Zap, Github, AlertTriangle } from "lucide-react";
import { runScenario, fetchDays, warmUp, ScenarioResponse } from "./api";
import Comparison from "./Comparison";
import Hosting from "./Hosting";
import HeroScene from "./HeroScene";
import "./index.css";
import "./ev-theme.css";

type Objective = "emissions" | "cost" | "peak";
type Tab = "simulator" | "comparison" | "hosting";

const OPT = "#3987e5";
const NAIVE = "#d95926";
const GRID = "#202A36";
const INK3 = "#5F6C7B";

const OBJECTIVES: { key: Objective; label: string }[] = [
  { key: "emissions", label: "Min. CO₂" },
  { key: "cost", label: "Min. Cost" },
  { key: "peak", label: "Min. Peak" },
];

/** A reduction can be negative: optimizing one objective often worsens another
 *  on real grid data. Show that as an increase rather than a bare minus sign. */
function signed(pct: number) {
  return pct >= 0 ? `${pct}%` : `+${Math.abs(pct)}%`;
}
function deltaColor(pct: number) {
  return pct >= 0 ? "var(--ink)" : NAIVE;
}

/** The headline follows whatever is being optimized, so the hero number is
 *  always the metric the user actually asked the scheduler to improve. */
function headline(r: ScenarioResponse, objective: Objective) {
  if (objective === "cost") {
    return {
      pct: r.cost_reduction_pct,
      label: "lower charging cost",
      sub: `€${r.cost_naive} → €${r.cost_optimized} · ${r.ev_count} vehicles`,
    };
  }
  if (objective === "peak") {
    return {
      pct: r.peak_reduction_pct,
      label: "lower peak grid load",
      sub: `${r.peak_naive_kw} kW → ${r.peak_optimized_kw} kW`,
    };
  }
  return {
    pct: r.emissions_reduction_pct,
    label: "less CO₂ than charging on arrival",
    sub: `${r.emissions_naive_kg} kg → ${r.emissions_optimized_kg} kg · ${r.ev_count} vehicles`,
  };
}

function ChartTip({ active, payload, label, unit, digits = 1 }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tip">
      <div className="tipHour">{label}</div>
      {payload.map((p: any) => (
        <div className="tipRow" key={p.dataKey}>
          <span className="legendSwatch" style={{ background: p.stroke }} />
          {p.name}
          <b>{Number(p.value).toFixed(digits)} {unit}</b>
        </div>
      ))}
    </div>
  );
}

export default function App() {
  const [evCount, setEvCount] = useState(80);
  const [chargerKw, setChargerKw] = useState(7);
  const [feederKw, setFeederKw] = useState(0); // 0 = unconstrained
  // Off by default so the landing view is the theoretical best; switching it on
  // is what a real scheduler, which cannot see tomorrow, would actually get.
  const [useForecast, setUseForecast] = useState(false);
  const [objective, setObjective] = useState<Objective>("emissions");
  const [methodOpen, setMethodOpen] = useState(false);
  // Tab lives in the URL hash so a pane can be linked to directly, and so a
  // reload keeps you where you were.
  const [tab, setTab] = useState<Tab>(
    () => {
      const h = window.location.hash.replace("#", "");
      return h === "comparison" || h === "hosting" ? (h as Tab) : "simulator";
    },
  );
  const selectTab = (t: Tab) => {
    setTab(t);
    window.history.replaceState(null, "", t === "simulator" ? "#" : `#${t}`);
  };
  const [result, setResult] = useState<ScenarioResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // SMIL animations inside the SVG are not reachable by the CSS media query,
  // so the preference has to be read in JS and passed down.
  const prefersReduced =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const [days, setDays] = useState<string[]>([]);
  const [day, setDay] = useState<string>("");

  // Keep the latest control values addressable from the mount effect without
  // making it re-run (and re-fire a request) on every slider nudge.
  const latest = useRef({ evCount, chargerKw, feederKw, objective, day, useForecast });
  latest.current = { evCount, chargerKw, feederKw, objective, day, useForecast };

  const run = useCallback(async (overrideDay?: string) => {
    setLoading(true);
    setError(null);
    const c = latest.current;
    const chosenDay = overrideDay ?? c.day;
    try {
      setResult(
        await runScenario({
          ev_count: c.evCount,
          charger_kw: c.chargerKw,
          arrival_hour: 18,
          deadline_hour: 7,
          energy_per_vehicle_kwh: 9.2,
          objective: c.objective,
          region: "ES",
          ...(chosenDay ? { day: chosenDay } : {}),
          ...(c.feederKw > 0 ? { feeder_capacity_kw: c.feederKw } : {}),
        ...(c.useForecast ? { use_forecast: true } : {}),
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // Land on a populated page. An empty dashboard behind a "Run" button is a
  // dead first impression, and the default night is already representative.
  useEffect(() => {
    warmUp();
    fetchDays()
      .then((d) => {
        setDays(d.days);
        setDay(d.default);
        return run(d.default);
      })
      .catch(() => run());
  }, [run]);

  const head = result ? headline(result, objective) : null;

  // Plot the charging night in the order it actually happens: 18:00 -> 07:00.
  // Indexed 0-23 the night is split, so the evening arrival spike lands on the
  // far right while the hours it shifts into sit on the far left — which reads
  // as if the optimizer acted before anyone got home. Hours 08-17 are outside
  // the window and carry no EV load, so they are dropped rather than reordered.
  const night = result
    ? [...result.hourly.slice(18), ...result.hourly.slice(0, 8)].map((p) => ({
        ...p,
        // Same stitch as the measured curve, so forecast and actual line up hour
        // for hour rather than being offset by the window wrap.
        carbon_forecast: result.hourly_forecast
          ? result.hourly_forecast[p.hour]
          : undefined,
      }))
    : [];

  return (
    <div className="page">
      <div className="gridOverlay" />
      <div className="evFloor" aria-hidden="true" />

      <header className="header">
        <div className="brand">
          <div className="brandMark">
            <Zap size={17} color="#fff" strokeWidth={2.4} />
          </div>
          <div>
            <div className="brandName">GridSense</div>
            <div className="brandTag">carbon-aware charge scheduling · Spanish grid</div>
          </div>
        </div>
        {tab === "simulator" && (
        <div className="objectiveToggle">
          {OBJECTIVES.map((o) => (
            <button
              key={o.key}
              onClick={() => setObjective(o.key)}
              className={`objectiveBtn ${objective === o.key ? "active" : ""}`}
            >
              {o.label}
            </button>
          ))}
        </div>
        )}
      </header>

      <nav className="tabs">
        <button className={`tab ${tab === "simulator" ? "active" : ""}`}
          onClick={() => selectTab("simulator")}>Simulator</button>
        <button className={`tab ${tab === "comparison" ? "active" : ""}`}
          onClick={() => selectTab("comparison")}>Existing vs GridSense</button>
        <button className={`tab ${tab === "hosting" ? "active" : ""}`}
          onClick={() => selectTab("hosting")}>Grid headroom</button>
      </nav>

      {tab === "simulator" && (
        <section className="masthead">
          <div>
            <span className="mastKicker">
              <span className="mastDot" aria-hidden="true" />
              Measured grid data · <b>ENTSO-E Spain</b>
            </span>
            <h1 className="mastTitle">
              Charge when the grid is{" "}
              <span className="lit">actually clean</span>.
            </h1>
            <p className="mastSub">
              Most EVs charge the moment their owner gets home, straight into the evening
              peak. This schedules the same energy against real carbon intensity and real
              prices — and reports honestly how little that buys on most nights.
            </p>
            <div className="mastFacts">
              <div className="mastFact">
                <span className="mastFactVal">1,444</span>
                <span className="mastFactKey">nights backtested</span>
              </div>
              <div className="mastFact">
                <span className="mastFactVal">6.3×</span>
                <span className="mastFactKey">hosting capacity</span>
              </div>
              <div className="mastFact">
                <span className="mastFactVal">71%</span>
                <span className="mastFactKey">captured by forecast</span>
              </div>
            </div>
          </div>
          <HeroScene reduced={prefersReduced} />
        </section>
      )}

      <main className="main">
        {tab === "comparison" && <Comparison />}
        {tab === "hosting" && <Hosting />}

        {tab === "simulator" && (
        <>
        <section className="card">
          <div className="eyebrow" style={{ marginBottom: 14 }}>Scenario</div>
          <div className="controls">
            <div className="field">
              <label>EVs in neighbourhood</label>
              <input type="range" min={10} max={200} value={evCount}
                onChange={(e) => setEvCount(+e.target.value)} />
              <div className="fieldValue">{evCount} vehicles</div>
            </div>
            <div className="field">
              <label>Charger rating</label>
              <input type="range" min={1.4} max={11} step={0.1} value={chargerKw}
                onChange={(e) => setChargerKw(+e.target.value)} />
              <div className="fieldValue">{chargerKw.toFixed(1)} kW</div>
            </div>
            <div className="field">
              <label>Feeder capacity</label>
              <input type="range" min={0} max={1200} step={25} value={feederKw}
                onChange={(e) => setFeederKw(+e.target.value)} />
              <div className="fieldValue">
                {feederKw === 0 ? <em>unconstrained</em> : `${feederKw} kW transformer`}
              </div>
            </div>
            <div className="field">
              <label>Measured grid night</label>
              <select className="daySelect" value={day} onChange={(e) => setDay(e.target.value)}>
                {days.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
              <div className="fieldValue"><em>{days.length} real nights</em></div>
            </div>
            <div className="field fieldWide">
              <label>Carbon signal the scheduler sees</label>
              <div className="segmented">
                <button className={!useForecast ? "active" : ""}
                  onClick={() => setUseForecast(false)}>Perfect foresight</button>
                <button className={useForecast ? "active" : ""}
                  onClick={() => setUseForecast(true)}>Day-ahead forecast</button>
              </div>
              <div className="fieldValue">
                <em>{useForecast ? "what a real scheduler sees" : "upper bound"}</em>
              </div>
            </div>
            <button className="runBtn" onClick={() => run()} disabled={loading}>
              {loading ? "Solving…" : "Run simulation"}
            </button>
          </div>
          {error && <div className="errorText">{error}</div>}
        </section>

        {result && head && (
          <>
            <section className="hero">
              <div className="heroMain">
                <div className="eyebrow">Night of {result.day}</div>
                <div className="heroValue" style={{ color: deltaColor(head.pct) }}>
                  {signed(head.pct)}
                </div>
                <div className="heroLabel">{head.label}</div>
                <div className="heroSub">{head.sub}</div>
                {result.used_forecast && (
                  <div className="heroSub" style={{ color: NAIVE }}>
                    scheduled on the day-ahead forecast, scored on what happened
                  </div>
                )}
              </div>
              <div className="heroNote">
                This is the <strong>median</strong> night of 2018, not the best one. Across the
                full year the median saving is <strong>3.3%</strong> and the fleet-wide total{" "}
                <strong>10.4%</strong> — but <strong>38% of nights save under 1%</strong> while
                17% save over 20%. Pick a different night above to see the spread.
              </div>
            </section>

            {result.feeder_capacity_kw !== null && result.naive_overload_hours > 0 && (
              <div className="strainBanner">
                <AlertTriangle size={16} color={NAIVE} style={{ flex: "none", marginTop: 1 }} />
                <span>
                  Charging on arrival overloads the {result.feeder_capacity_kw} kW transformer for{" "}
                  <strong>{result.naive_overload_hours}h</strong>, peaking{" "}
                  <strong>{result.naive_overload_peak_kw} kW</strong> above its limit. The optimized
                  schedule stays inside it — this shared limit is the only constraint that couples
                  vehicles, and the only reason the schedule needs a solver at all.
                </span>
              </div>
            )}

            <section className="statsGrid">
              {objective !== "emissions" && (
                <div className="statCard">
                  <div className="statLabel">Grid CO₂</div>
                  <div className="statValue" style={{ color: deltaColor(result.emissions_reduction_pct) }}>
                    {signed(result.emissions_reduction_pct)}
                  </div>
                  <div className="statSub">{result.emissions_naive_kg} → {result.emissions_optimized_kg} kg</div>
                </div>
              )}
              {objective !== "cost" && (
                <div className="statCard">
                  <div className="statLabel">Charging cost</div>
                  <div className="statValue" style={{ color: deltaColor(result.cost_reduction_pct) }}>
                    {signed(result.cost_reduction_pct)}
                  </div>
                  <div className="statSub">€{result.cost_naive} → €{result.cost_optimized}</div>
                </div>
              )}
              {objective !== "peak" && (
                <div className="statCard">
                  <div className="statLabel">Peak grid load</div>
                  <div className="statValue" style={{ color: deltaColor(result.peak_reduction_pct) }}>
                    {signed(result.peak_reduction_pct)}
                  </div>
                  <div className="statSub">{result.peak_naive_kw} → {result.peak_optimized_kw} kW</div>
                </div>
              )}
              <div className="statCard">
                <div className="statLabel">Energy scheduled</div>
                <div className="statValue">{result.energy_scheduled_kwh} kWh</div>
                <div className="statSub">{result.ev_count} vehicles · {result.region}</div>
                <div className="battery" aria-hidden="true">
                  <div className="batteryCell"
                    style={{ ["--soc" as any]: `${Math.min(100, (result.ev_count / 200) * 100)}%` }} />
                  <div className="batteryTip" />
                </div>
              </div>
            </section>

            <section className="card">
              <div className="chartHeader">
                <div>
                  <div className="chartTitle">Neighbourhood grid load</div>
                  <div className="chartMeta">kW · 18:00 → 07:00, the hours a car is plugged in · 00–07 is the next morning</div>
                  <div className="shiftHint" style={{ marginTop: 6 }}>
                    <span className="shiftTrack" aria-hidden="true"><span className="shiftDot" /></span>
                    load moves off the arrival spike into cleaner hours
                  </div>
                </div>
                <div className="legend">
                  <span className="legendItem">
                    <span className="legendSwatch" style={{ background: NAIVE }} />
                    Charging on arrival
                  </span>
                  <span className="legendItem">
                    <span className="legendSwatch" style={{ background: OPT }} />
                    Optimized
                  </span>
                </div>
              </div>
              <ResponsiveContainer width="100%" height={290}>
                <AreaChart data={night} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="label" interval={1} tick={{ fill: INK3, fontSize: 11 }}
                    axisLine={{ stroke: GRID }} tickLine={false} />
                  <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false}
                    width={54} tickFormatter={(v: number) => v.toLocaleString()} />
                  <Tooltip content={<ChartTip unit="kW" />} cursor={{ stroke: GRID }} />
                  <Area type="stepAfter" dataKey="naive_kw" name="On arrival" stroke={NAIVE}
                    fill={NAIVE} fillOpacity={0.1} strokeWidth={2} dot={false} />
                  <Area type="stepAfter" dataKey="optimized_kw" name="Optimized" stroke={OPT}
                    fill={OPT} fillOpacity={0.1} strokeWidth={2} dot={false} />
                  {result.feeder_capacity_kw !== null && (
                    <ReferenceLine y={result.feeder_capacity_kw} stroke={NAIVE} strokeWidth={1.5}
                      strokeDasharray="5 4"
                      label={{ value: `feeder limit ${result.feeder_capacity_kw} kW`,
                        position: "insideTopRight", fill: NAIVE, fontSize: 10.5 }} />
                  )}
                </AreaChart>
              </ResponsiveContainer>
            </section>

            <section className="card">
              <div className="chartHeader">
                <div>
                  <div className="chartTitle">Grid carbon intensity</div>
                  <div className="chartMeta">
                    gCO₂/kWh · measured from the ENTSO-E generation mix · average, not marginal
                  </div>
                </div>
                {result.used_forecast && (
                  <div className="legend">
                    <span className="legendItem">
                      <span className="legendSwatch" style={{ background: OPT }} />Actual
                    </span>
                    <span className="legendItem">
                      <span className="legendSwatch" style={{ background: NAIVE }} />
                      Forecast the scheduler saw
                    </span>
                  </div>
                )}
              </div>
              <ResponsiveContainer width="100%" height={170}>
                <LineChart data={night} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="label" interval={1} tick={{ fill: INK3, fontSize: 11 }}
                    axisLine={{ stroke: GRID }} tickLine={false} />
                  <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false}
                    width={54} tickCount={4}
                    domain={[
                      (min: number) => Math.floor((min - 10) / 25) * 25,
                      (max: number) => Math.ceil((max + 10) / 25) * 25,
                    ]} />
                  <Tooltip content={<ChartTip unit="gCO₂/kWh" digits={0} />} cursor={{ stroke: GRID }} />
                  <Line type="linear" dataKey="carbon_intensity" name="Actual"
                    stroke={OPT} strokeWidth={2} dot={false} isAnimationActive={false} />
                  {result.used_forecast && (
                    <Line type="linear" dataKey="carbon_forecast" name="Day-ahead forecast"
                      stroke={NAIVE} strokeWidth={1.75} strokeDasharray="5 4" dot={false}
                      isAnimationActive={false} />
                  )}
                </LineChart>
              </ResponsiveContainer>
            </section>
          </>
        )}

        </>
        )}

        {tab === "simulator" && (
        <section className="card">
          <button className="methodToggle" onClick={() => setMethodOpen(!methodOpen)}>
            <span className="eyebrow">Methodology &amp; limitations</span>
            <ChevronDown size={16} color={INK3}
              style={{ transform: methodOpen ? "rotate(180deg)" : "none", transition: "transform .15s" }} />
          </button>
          {methodOpen && (
            <>
              <p className="methodText">
                Each vehicle's charge requirement is scheduled by a linear program minimizing the
                selected objective, subject to total energy delivered by the deadline and per-session
                power staying under the charger rating. Every curve shown is measured, not modelled:
                carbon intensity is derived from the ENTSO-E Spanish generation mix weighted by IPCC
                AR5 lifecycle emission factors, and price is the day-ahead market clearing price plus
                the flat PVPC access component.
              </p>
              <p className="methodText">
                The feeder limit models a shared street transformer, and it is the only constraint
                coupling vehicles to one another. Without it the problem separates — each vehicle
                independently fills its own cleanest hours, and a greedy loop matches the linear
                program to within 1e-6. Set a limit and greedy breaches it, by 485 kW against a
                180 kW transformer in testing, while the LP schedules around it.
              </p>
              <p className="methodText">
                <em>Limitations.</em> This is average carbon intensity, not marginal — the emissions
                of the average kWh rather than the next one, which is what load shifting actually
                moves. The residential baseline is the one remaining synthetic input, since ENTSO-E
                reports system-wide load that cannot be scaled to a single feeder without an
                assumption. Objectives genuinely conflict: the cheapest hour and the cleanest hour
                coincide on only 14% of nights, so optimizing cost can raise emissions. Those are
                shown as increases rather than hidden.
              </p>
            </>
          )}
        </section>
        )}
      </main>

      <footer className="footer">
        <span>ENTSO-E Spain 2018 · generation mix + day-ahead prices · emission factors IPCC AR5</span>
        <a href="https://github.com/adityaayushman/GRIDSENSE" className="footerLink"
          target="_blank" rel="noreferrer">
          <Github size={14} /> Source
        </a>
      </footer>
    </div>
  );
}
