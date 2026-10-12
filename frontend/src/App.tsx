import { useCallback, useEffect, useRef, useState } from "react";
import {
  AreaChart, Area, LineChart, Line, ReferenceLine,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import {
  ChevronDown, Zap, Github, AlertTriangle,
  Command, Link2, Download, Keyboard,
} from "lucide-react";
import { runScenario, fetchDays, warmUp, ScenarioResponse, GATE_MIN_SAVING_PCT } from "./api";
import Comparison from "./Comparison";
import Hosting from "./Hosting";
import HeroScene from "./HeroScene";
import Regions from "./Regions";
import Control from "./Control";
import India from "./India";
import Segmented from "./Segmented";
import Landing from "./Landing";
import hosting from "./data/hosting.json";
import CommandPalette, { Command as Cmd } from "./CommandPalette";
import Shortcuts from "./Shortcuts";
import { ToastHost, useToast } from "./toast";
import { usePrefersReduced, useCountUp, useReveal } from "./motion";
import "./design.css";
import "./index.css";
import "./ev-theme.css";
import "./landing.css";
import "./chrome.css";

type Objective = "emissions" | "cost" | "peak";
type Tab = "simulator" | "comparison" | "hosting" | "regions" | "control" | "india";

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

/** The same, counted up. Sign is taken from the target so the label never
 *  flickers between "increase" and "reduction" while the number travels. */
function CountPct({ pct, reduced }: { pct: number; reduced: boolean }) {
  const shown = useCountUp(pct, reduced);
  const v = Math.abs(shown).toFixed(1);
  return <>{pct >= 0 ? `${v}%` : `+${v}%`}</>;
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

/**
 * Scenario controls live in the query string so a run can be linked to.
 *
 * The tab stays in the hash and the controls in the search params: they change
 * on different cadences, and mixing them would mean rewriting the whole
 * fragment every time a slider moves.
 */
const PARAMS = new URLSearchParams(window.location.search);
const num = (key: string, fallback: number) => {
  const raw = PARAMS.get(key);
  const n = raw === null ? NaN : Number(raw);
  return Number.isFinite(n) ? n : fallback;
};
const flag = (key: string) => PARAMS.get(key) === "1";

function App() {
  const toast = useToast();
  const [evCount, setEvCount] = useState(() => num("ev", 80));
  const [chargerKw, setChargerKw] = useState(() => num("kw", 7));
  const [feederKw, setFeederKw] = useState(() => num("feeder", 0)); // 0 = unconstrained
  // Off by default so the landing view is the theoretical best; switching it on
  // is what a real scheduler, which cannot see tomorrow, would actually get.
  const [useForecast, setUseForecast] = useState(() => flag("fc"));
  // The forecast gate only means something when scheduling on a forecast; it
  // stays off by default so the plain forecast result remains visible.
  const [gate, setGate] = useState(() => flag("gate"));
  const [v2g, setV2g] = useState(() => flag("v2g"));
  const [objective, setObjective] = useState<Objective>(() => {
    const o = PARAMS.get("obj");
    return o === "cost" || o === "peak" || o === "emissions" ? o : "emissions";
  });
  const [methodOpen, setMethodOpen] = useState(false);
  // Tab lives in the URL hash so a pane can be linked to directly, and so a
  // reload keeps you where you were.
  const [tab, setTab] = useState<Tab>(
    () => {
      const h = window.location.hash.replace("#", "");
      return ["comparison", "hosting", "regions", "control", "india"].includes(h)
        ? (h as Tab) : "simulator";
    },
  );
  const selectTab = (t: Tab) => {
    setTab(t);
    window.history.replaceState(null, "", `#${t}`);
  };

  // The landing page is the default view, but a link straight to a pane must
  // skip it — so an existing hash means the visitor already chose a
  // destination. Leaving the dashboard clears the hash rather than pushing, so
  // Back still leaves the site instead of ping-ponging through the gate.
  const [entered, setEntered] = useState(() => window.location.hash.length > 1);
  const enter = useCallback(() => {
    setEntered(true);
    window.history.replaceState(null, "", "#simulator");
    window.scrollTo({ top: 0, behavior: "auto" });
  }, []);
  const leave = useCallback(() => {
    setEntered(false);
    window.history.replaceState(null, "", window.location.pathname);
    window.scrollTo({ top: 0, behavior: "auto" });
  }, []);
  const [result, setResult] = useState<ScenarioResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // SMIL and rAF-driven motion sit outside the reach of the CSS media query,
  // so the preference is read in JS and threaded through.
  const prefersReduced = usePrefersReduced();
  const stage = useRef<HTMLDivElement>(null);

  const onStageMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (prefersReduced) return;
    const el = stage.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    // -1..1 from the centre, so layers can lean either way.
    el.style.setProperty("--px", String(((e.clientX - r.left) / r.width - 0.5) * 2));
    el.style.setProperty("--py", String(((e.clientY - r.top) / r.height - 0.5) * 2));
  };
  const onStageLeave = () => {
    stage.current?.style.setProperty("--px", "0");
    stage.current?.style.setProperty("--py", "0");
  };
  const [days, setDays] = useState<string[]>([]);
  const [day, setDay] = useState<string>(() => PARAMS.get("day") ?? "");

  // Keep the latest control values addressable from the mount effect without
  // making it re-run (and re-fire a request) on every slider nudge.
  const latest = useRef({ evCount, chargerKw, feederKw, objective, day, useForecast, gate, v2g });
  latest.current = { evCount, chargerKw, feederKw, objective, day, useForecast, gate, v2g };

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
        ...(c.useForecast && c.gate ? { gate_min_saving_pct: GATE_MIN_SAVING_PCT } : {}),
        ...(c.v2g ? { allow_v2g: true } : {}),
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // Mirror the controls into the address bar after each run, so the URL always
  // describes what is on screen and can be copied at any moment.
  useEffect(() => {
    if (!entered) return;
    const p = new URLSearchParams();
    if (evCount !== 80) p.set("ev", String(evCount));
    if (chargerKw !== 7) p.set("kw", String(chargerKw));
    if (feederKw > 0) p.set("feeder", String(feederKw));
    if (objective !== "emissions") p.set("obj", objective);
    if (useForecast) p.set("fc", "1");
    if (useForecast && gate) p.set("gate", "1");
    if (v2g) p.set("v2g", "1");
    if (day) p.set("day", day);
    const qs = p.toString();
    window.history.replaceState(
      null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}#${tab}`,
    );
  }, [entered, evCount, chargerKw, feederKw, objective, useForecast, gate, v2g, day, tab]);

  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  const share = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      toast("Link copied — it reopens this exact scenario");
    } catch {
      // Clipboard access is refused outside a secure context and in some
      // embedded views; the URL is already correct, so say so rather than fail.
      toast("Copy blocked — the address bar already holds this scenario", "warn");
    }
  }, [toast]);

  const exportCsv = useCallback(() => {
    if (!result) return toast("Nothing to export yet", "warn");
    const head = "hour,label,naive_kw,optimized_kw,carbon_gco2eq_per_kwh,price_eur_per_kwh";
    const rows = result.hourly.map((h) =>
      [h.hour, h.label, h.naive_kw, h.optimized_kw, h.carbon_intensity, h.price].join(","));
    const blob = new Blob([[head, ...rows].join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `gridsense-${result.day ?? "night"}-${objective}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast(`Exported ${rows.length} hours as CSV`);
  }, [result, objective, toast]);

  const stepDay = useCallback((delta: number) => {
    if (!days.length) return;
    const i = days.indexOf(day);
    const next = days[(i < 0 ? 0 : i + delta + days.length) % days.length];
    setDay(next);
    run(next);
  }, [days, day, run]);

  const TABS: { key: Tab; label: string }[] = [
    { key: "simulator", label: "Simulator" },
    { key: "comparison", label: "Existing vs GridSense" },
    { key: "hosting", label: "Grid headroom" },
    { key: "regions", label: "Two grids" },
    { key: "control", label: "Rolling control" },
    { key: "india", label: "India" },
  ];

  const commands: Cmd[] = [
    ...TABS.map((t, i) => ({
      id: `go-${t.key}`, group: "Go to", label: t.label, hint: String(i + 1),
      keywords: "pane tab view",
      run: () => { setEntered(true); selectTab(t.key); },
    })),
    { id: "go-home", group: "Go to", label: "Project overview", hint: "H",
      keywords: "landing home about", run: leave },
    ...OBJECTIVES.map((o) => ({
      id: `obj-${o.key}`, group: "Objective", label: `Minimise ${o.label.toLowerCase()}`,
      keywords: "optimise target carbon cost peak",
      run: () => { setEntered(true); selectTab("simulator"); setObjective(o.key); },
    })),
    { id: "t-v2g", group: "Toggle", label: `${v2g ? "Disable" : "Enable"} vehicle-to-grid`,
      hint: "V", keywords: "v2g discharge export battery", run: () => setV2g((x) => !x) },
    { id: "t-fc", group: "Toggle",
      label: `${useForecast ? "Use perfect foresight" : "Use the day-ahead forecast"}`,
      hint: "F", keywords: "forecast prediction foresight", run: () => setUseForecast((x) => !x) },
    { id: "a-run", group: "Actions", label: "Re-run this scenario", hint: "R",
      keywords: "solve refresh compute", run: () => run() },
    { id: "a-next", group: "Actions", label: "Next night", hint: "]",
      keywords: "day date advance", run: () => stepDay(1) },
    { id: "a-prev", group: "Actions", label: "Previous night", hint: "[",
      keywords: "day date back", run: () => stepDay(-1) },
    { id: "a-share", group: "Actions", label: "Copy a link to this scenario", hint: "S",
      keywords: "share url permalink copy", run: share },
    { id: "a-csv", group: "Actions", label: "Export the schedule as CSV", hint: "E",
      keywords: "download data export csv", run: exportCsv },
    { id: "a-keys", group: "Actions", label: "Keyboard shortcuts", hint: "?",
      keywords: "help keys bindings", run: () => setHelpOpen(true) },
    { id: "a-src", group: "Actions", label: "Open the source on GitHub",
      keywords: "code repository github",
      run: () => window.open("https://github.com/adityaayushman/GRIDSENSE", "_blank") },
  ];

  // Global keys. Anything typed into a field belongs to that field, so the
  // handler stands down whenever an editable element holds focus.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = !!t && (t.isContentEditable ||
        ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));

      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((x) => !x);
        return;
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      if (paletteOpen || helpOpen) return;

      const k = e.key.toLowerCase();
      if (e.key === "?") { e.preventDefault(); setHelpOpen(true); return; }
      if (k >= "1" && k <= "6") {
        const t2 = TABS[Number(k) - 1];
        if (t2) { setEntered(true); selectTab(t2.key); }
        return;
      }
      if (!entered) return;
      if (k === "h") leave();
      else if (k === "r") run();
      else if (k === "s") share();
      else if (k === "e") exportCsv();
      else if (k === "v") setV2g((x) => !x);
      else if (k === "f") setUseForecast((x) => !x);
      else if (e.key === "[") stepDay(-1);
      else if (e.key === "]") stepDay(1);
      else if (k === "c") {
        const i = OBJECTIVES.findIndex((o) => o.key === objective);
        setObjective(OBJECTIVES[(i + 1) % OBJECTIVES.length].key);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

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

  if (!entered) {
    return (
      <>
        <Landing onEnter={enter} onPalette={() => setPaletteOpen(true)} />
        <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)}
          commands={commands} />
        <Shortcuts open={helpOpen} onClose={() => setHelpOpen(false)} />
      </>
    );
  }

  return (
    <div className="page">
      <div className="gridOverlay" />
      <div className="evFloor" aria-hidden="true" />

      <header className="header">
        <button className="brand brandHome" onClick={leave}
          title="Back to the overview">
          <div className="brandMark">
            <Zap size={17} color="#fff" strokeWidth={2.4} />
          </div>
          <div>
            <div className="brandName">GridSense</div>
            <div className="brandTag">carbon-aware charge scheduling · Spanish grid</div>
          </div>
        </button>
        <div className="headTools">
          {tab === "simulator" && (
            <Segmented
              className="objectiveToggle"
              options={OBJECTIVES.map((o) => ({ key: o.key, label: o.label }))}
              value={objective}
              onChange={setObjective}
            />
          )}
          <button className="toolBtn" onClick={() => setPaletteOpen(true)}
            title="Command palette (⌘K)">
            <Command size={14} strokeWidth={2.2} /><span className="kbd">K</span>
          </button>
          {tab === "simulator" && (
            <>
              <button className="toolBtn" onClick={share} title="Copy a link to this scenario (S)">
                <Link2 size={14} strokeWidth={2.2} />
              </button>
              <button className="toolBtn" onClick={exportCsv} title="Export as CSV (E)">
                <Download size={14} strokeWidth={2.2} />
              </button>
            </>
          )}
          <button className="toolBtn" onClick={() => setHelpOpen(true)}
            title="Keyboard shortcuts (?)">
            <Keyboard size={14} strokeWidth={2.2} />
          </button>
        </div>
      </header>

      <nav className="tabs">
        <button className={`tab ${tab === "simulator" ? "active" : ""}`}
          onClick={() => selectTab("simulator")}>Simulator</button>
        <button className={`tab ${tab === "comparison" ? "active" : ""}`}
          onClick={() => selectTab("comparison")}>Existing vs GridSense</button>
        <button className={`tab ${tab === "hosting" ? "active" : ""}`}
          onClick={() => selectTab("hosting")}>Grid headroom</button>
        <button className={`tab ${tab === "regions" ? "active" : ""}`}
          onClick={() => selectTab("regions")}>Two grids</button>
        <button className={`tab ${tab === "control" ? "active" : ""}`}
          onClick={() => selectTab("control")}>Rolling control</button>
        <button className={`tab ${tab === "india" ? "active" : ""}`}
          onClick={() => selectTab("india")}>India</button>
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
                {/* Read from the generated data, not typed in: this figure was
                    hardcoded as 6.3x and went stale the moment the residential
                    baseline was recalibrated. */}
                <span className="mastFactVal">{hosting.headline.gain}×</span>
                <span className="mastFactKey">hosting capacity</span>
              </div>
              <div className="mastFact">
                <span className="mastFactVal">71%</span>
                <span className="mastFactKey">captured by forecast</span>
              </div>
            </div>
          </div>
          <div className="heroStage" ref={stage}
            onMouseMove={onStageMove} onMouseLeave={onStageLeave}>
            <HeroScene reduced={prefersReduced} />
          </div>
        </section>
      )}

      <main className="main">
        {tab === "comparison" && <div key="cmp" className="paneEnter"><Comparison /></div>}
        {tab === "hosting" && <div key="hst" className="paneEnter"><Hosting /></div>}
        {tab === "regions" && <div key="rgn" className="paneEnter"><Regions /></div>}
        {tab === "control" && <div key="ctl" className="paneEnter"><Control /></div>}
        {tab === "india" && <div key="ind" className="paneEnter"><India /></div>}

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
              <Segmented
                options={[
                  { key: "actual", label: "Perfect foresight" },
                  { key: "forecast", label: "Day-ahead forecast" },
                ]}
                value={useForecast ? "forecast" : "actual"}
                onChange={(v) => setUseForecast(v === "forecast")}
              />
              <div className="fieldValue">
                <em>{useForecast ? "what a real scheduler sees" : "upper bound"}</em>
              </div>
            </div>
            {useForecast && (
              <div className="field">
                <label>Forecast gate</label>
                <Segmented
                  options={[
                    { key: "off", label: "Always schedule" },
                    { key: "on", label: `Gate at ${GATE_MIN_SAVING_PCT}%` },
                  ]}
                  value={gate ? "on" : "off"}
                  onChange={(x) => setGate(x === "on")}
                />
                <div className="fieldValue">
                  <em>{gate ? "charge on arrival if the forecast sees little to gain" : "trust the forecast every night"}</em>
                </div>
              </div>
            )}
            <div className="field">
              <label>Vehicle-to-grid</label>
              <Segmented
                options={[
                  { key: "off", label: "Charge only" },
                  { key: "on", label: "Discharge too" },
                ]}
                value={v2g ? "on" : "off"}
                onChange={(x) => setV2g(x === "on")}
              />
              <div className="fieldValue">
                <em>{v2g ? "6 kWh export cap per car" : "one-way"}</em>
              </div>
            </div>
            <button className="runBtn" onClick={() => run()} disabled={loading}>
              {loading ? (
                <span className="solving">
                  <span className="solvingCells" aria-hidden="true">
                    <i /><i /><i /><i />
                  </span>
                  Solving
                </span>
              ) : "Run simulation"}
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
                  <CountPct pct={head.pct} reduced={prefersReduced} />
                </div>
                <div className="heroLabel">{head.label}</div>
                <div className="heroSub">{head.sub}</div>
                {result.used_v2g && result.exported_kwh > 0 && (
                  <div className="heroSub" style={{ color: "#199e70" }}>
                    {result.exported_kwh} kWh exported back to the grid
                  </div>
                )}
                {result.used_forecast && (
                  <div className="heroSub" style={{ color: NAIVE }}>
                    scheduled on the day-ahead forecast, scored on what happened
                  </div>
                )}
                {result.gate_applied && (
                  <div className="heroSub" style={{ color: NAIVE }}>
                    {result.gate_acted
                      ? `gate open: the forecast expected a ${result.gate_expected_saving_pct}% saving, so it scheduled`
                      : `gate closed: the forecast expected only ${result.gate_expected_saving_pct}%, so the fleet charged on arrival`}
                  </div>
                )}
                {!result.gate_applied && result.gate_reason && gate && (
                  <div className="heroSub">gate off here: {result.gate_reason}</div>
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
                    <CountPct pct={result.emissions_reduction_pct} reduced={prefersReduced} />
                  </div>
                  <div className="statSub">{result.emissions_naive_kg} → {result.emissions_optimized_kg} kg</div>
                </div>
              )}
              {objective !== "cost" && (
                <div className="statCard">
                  <div className="statLabel">Charging cost</div>
                  <div className="statValue" style={{ color: deltaColor(result.cost_reduction_pct) }}>
                    <CountPct pct={result.cost_reduction_pct} reduced={prefersReduced} />
                  </div>
                  <div className="statSub">€{result.cost_naive} → €{result.cost_optimized}</div>
                </div>
              )}
              {objective !== "peak" && (
                <div className="statCard">
                  <div className="statLabel">Peak grid load</div>
                  <div className="statValue" style={{ color: deltaColor(result.peak_reduction_pct) }}>
                    <CountPct pct={result.peak_reduction_pct} reduced={prefersReduced} />
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
              <div className="chartWipe" key={`load-${result.day}-${result.used_forecast}-${objective}`}>
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
                    fill={OPT} fillOpacity={0.1} strokeWidth={2} dot={false}
                    className={prefersReduced ? undefined : "flowPath"} />
                  {result.feeder_capacity_kw !== null && (
                    <ReferenceLine y={result.feeder_capacity_kw} stroke={NAIVE} strokeWidth={1.5}
                      strokeDasharray="5 4"
                      label={{ value: `feeder limit ${result.feeder_capacity_kw} kW`,
                        position: "insideTopRight", fill: NAIVE, fontSize: 10.5 }} />
                  )}
                </AreaChart>
              </ResponsiveContainer>
              </div>
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

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)}
        commands={commands} />
      <Shortcuts open={helpOpen} onClose={() => setHelpOpen(false)} />
    </div>
  );
}

/** useToast has to be called under the provider, so the tree is split here. */
export default function AppRoot() {
  return (
    <ToastHost>
      <App />
    </ToastHost>
  );
}
