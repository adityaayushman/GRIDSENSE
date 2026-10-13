import { createContext, useContext, useEffect, useState } from "react";
import {
  BarChart, Bar, ComposedChart, Line, Cell, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceArea, ReferenceLine, LabelList,
} from "recharts";
import results from "./data/results.json";
import mpc from "./data/mpc.json";
import { usePrefersReduced, useReveal } from "./motion";

/**
 * Every figure here reads data/results.json, which ml/export_results.py builds from the
 * analyses' own artifacts. Nothing on this page is typed in except the history of what
 * was published before (which is history, not a result).
 *
 * Colour follows the project's validated palette on its dark surface: blue for the
 * thing the chart is about, orange for the contrast, grey for context. Where one bar is
 * the point it is blue and the rest are grey (emphasis) rather than a hue per bar.
 */
const BLUE = "#3987e5";
const ORANGE = "#d95926";
const AQUA = "#199e70";
const GREY = "#4a586b";
const RANGE = "#66768d";
const GRID = "#202A36";
const INK2 = "#9DAABB";
const INK3 = "#64748A";
const GAP = "#0A0F16";                              // the surface, for the 2px gap between fills
const BAND_COLOURS = ["#2b5f9e", "#3987e5", "#86b6ef", "#cde2fb"];   // ordinal ramp, brighter = bigger saving

const R: any = results;

/** True below a phone-ish width, so label columns can shrink and leave the bars room. */
function useNarrow(px = 640): boolean {
  const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && window.innerWidth <= px);
  useEffect(() => {
    const on = () => setNarrow(window.innerWidth <= px);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, [px]);
  return narrow;
}

const InView = createContext(false);

function Panel({ children }: { children: React.ReactNode }) {
  const reduced = usePrefersReduced();
  const { ref, shown } = useReveal<HTMLElement>(reduced);
  return (
    <InView.Provider value={shown}>
      <section ref={ref} className={`card reveal ${shown ? "isIn" : ""}`}>{children}</section>
    </InView.Provider>
  );
}

/** Holds a chart's exact height (so nothing shifts) and mounts it once its card is in view. */
function Chart({ height, children }: { height: number; children: React.ReactNode }) {
  const inView = useContext(InView);
  return <div style={{ height }}>{inView ? children : null}</div>;
}

function TableTwin({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <details className="tableTwin">
      <summary>View as a table</summary>
      <div className="tableWrap">
        <table className="runsTable">
          <thead><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
          <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </details>
  );
}

function Tip({ active, payload, label, fmt }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tip">
      {label !== undefined && <div className="tipHour">{label}</div>}
      {payload.filter((p: any) => p.value !== null && p.value !== undefined && p.dataKey !== "base").map((p: any) => (
        <div className="tipRow" key={p.dataKey}>
          <span className="legendSwatch" style={{ background: p.color || p.fill }} />
          {p.name}<b>{fmt ? fmt(p.value, p) : p.value}</b>
        </div>
      ))}
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="statCard card">
      <div className="statLabel">{label}</div>
      <div className="statValue">{value}</div>
      <div className="statSub">{sub}</div>
    </div>
  );
}

export default function Results() {
  const anim = !usePrefersReduced();
  const narrow = useNarrow();
  const sv: any[] = R.savings;
  const es = sv.find((s) => s.id === "es1518");
  const es25 = sv.find((s) => s.id === "es2025");
  const inn = sv.find((s) => s.id === "in_night");
  const ind = sv.find((s) => s.id === "in_day");
  const H = R.hosting;
  const S = R.sensitivity;
  const F = R.forecast;
  const C = R.control;
  const pct = (v: number, d = 1) => `${v.toFixed(d)}%`;

  // ---- 1. savings bands
  const bandData = sv.map((s) => ({ label: s.label, ...s.bands }));
  const bandNames: [string, string][] = [["lt1", "Under 1%"], ["b1_5", "1-5%"], ["b5_20", "5-20%"], ["gt20", "Over 20%"]];

  // ---- 2. hosting histogram of draws
  const gainsAll: number[] = H.draws.map((d: any) => d.gain);
  const first = Math.floor(Math.min(...gainsAll) * 2) / 2;
  const last = Math.floor(Math.max(...gainsAll) * 2) / 2;
  const hist = Array.from({ length: Math.round((last - first) / 0.5) + 1 }, (_, i) => first + i * 0.5).map((lo) => {
    const inBin = H.draws.filter((d: any) => d.gain >= lo && d.gain < lo + 0.5);
    const published = inBin.filter((d: any) => d.seed === 0).length;
    return { bin: `${lo.toFixed(1)}-${(lo + 0.5).toFixed(1)}×`, others: inBin.length - published, published };
  });
  const ratingData = H.ratings.map((r: any) => ({
    rating: `${r.rating_kw} kW`, base: r.gain_min, span: +(r.gain_max - r.gain_min).toFixed(2), median: r.gain,
    seeds: r.seeds,
  }));

  // ---- 3. sensitivity
  const sens = S.rows.map((r: any) => ({ ...r, label: r.what }));

  // ---- 4. forecast
  const fcData = [
    { grid: "Spain 2018 grid", lags: F.es2018.lags_only, dayahead: F.es2018.with_day_ahead, final: null },
    { grid: "Spain 2025 grid", lags: F.es2025.lags_only, dayahead: F.es2025.with_day_ahead, final: F.es2025.deployed },
  ];

  // ---- 5. control
  const ctrl = [
    { name: "One-shot plan", v: C.regret.oneshot, hl: true },
    { name: "Rolling, refreshed", v: C.regret.mpc, hl: false },
    { name: "Rolling, static", v: C.regret.mpc_static, hl: false },
    ...Object.entries(C.penalty).filter(([k]) => k !== "0.0").map(([k, v]: any) => ({ name: `Rolling + penalty ${k}`, v, hl: false })),
  ];

  // ---- 6. India windows
  const W = R.india.windows;
  const inData = [
    { name: "Spain overnight", v: es.median_pct, hl: false },
    { name: "India overnight", v: W.overnight.median_cut_pct, hl: false },
    { name: "India daytime", v: W.daytime.median_cut_pct, hl: true },
    { name: "India afternoon", v: W.afternoon.median_cut_pct, hl: false },
  ];

  return (
    <>
      <section className="hero">
        <div className="heroMain">
          <div className="eyebrow">The results · what the project found, including what did not work</div>
          <div className="heroValue" style={{ color: BLUE }}>{pct(es.median_pct)}</div>
          <div className="heroLabel">median overnight carbon saving in Spain. A smooth synthetic curve suggested over 30%.</div>
          <div className="heroSub">
            {pct(es.fleet_pct)} across the whole fleet · {pct(es.bands.lt1, 0)} of nights save under 1%
          </div>
        </div>
        <div className="heroNote">
          Carbon-aware charging saves little, and unevenly. <strong>Coordinating a street against its
          transformer matters more</strong>: about <strong>{H.median.toFixed(1)}×</strong> the EVs on
          the same unit, between {Math.min(...H.draws.map((d: any) => d.gain)).toFixed(1)}× and{" "}
          {Math.max(...H.draws.map((d: any) => d.gain)).toFixed(1)}× depending on the fleet drawn. Each chart
          has a table beneath it with the numbers.
        </div>
      </section>

      <details className="glossary">
        <summary>New here? Five terms used below</summary>
        <dl>
          <dt>Charging on arrival</dt>
          <dd>Every car starts at full power the moment it plugs in. The baseline everything is compared against.</dd>
          <dt>Hosting capacity</dt>
          <dd>How many EVs one street transformer can serve before a typical night overloads it.</dd>
          <dt>Fleet draw</dt>
          <dd>One random sample of arrival times, energy needs and charger sizes. Different draws give different answers, so the spread is reported.</dd>
          <dt>Noise band</dt>
          <dd>The range of answers from redrawing the same fleet. A change smaller than the band is not an effect.</dd>
          <dt>Captured saving</dt>
          <dd>The share of the best achievable carbon saving that a schedule built on a forecast actually delivers.</dd>
        </dl>
      </details>

      <section className="statsGrid statsSix">
        <Tile label="Spain overnight saving" value={pct(es.median_pct)} sub={`median of ${es.nights.toLocaleString()} nights, 2015-18`} />
        <Tile label="Spain 2025" value={pct(es25.median_pct)} sub={`${pct(es25.fleet_pct)} fleet-wide`} />
        <Tile label="Hosting capacity" value={`${H.median.toFixed(1)}×`} sub={`median of ${H.draws.length} fleet draws · 250 kW`} />
        <Tile label="2025 forecaster" value={pct(F.es2025.deployed, 0)} sub="of the achievable saving captured" />
        <Tile label="India overnight" value={pct(inn.median_pct, 2)} sub={`${pct(inn.bands.lt1, 0)} of nights under 1%`} />
        <Tile label="India daytime" value={pct(ind.median_pct, 2)} sub="the one window with a saving" />
      </section>

      {/* ---------- 1 */}
      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">How often does carbon-aware charging pay?</div>
            <div className="chartMeta">Share of nights in each saving band, by grid · same vehicles, same window</div>
          </div>
          <div className="legend">
            {bandNames.map(([k, name], i) => (
              <span className="legendItem" key={k}><span className="legendSwatch" style={{ background: BAND_COLOURS[i] }} />{name}</span>
            ))}
          </div>
        </div>
        <Chart height={260}><ResponsiveContainer width="100%" height="100%">
          <BarChart data={bandData} layout="vertical" margin={{ top: 4, right: 24, left: 8, bottom: 4 }} barCategoryGap={14}>
            <CartesianGrid stroke={GRID} horizontal={false} />
            <XAxis type="number" domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false}
              tickFormatter={(v) => `${v}%`} />
            <YAxis type="category" dataKey="label" width={narrow ? 92 : 160} tick={{ fill: INK2, fontSize: 12 }} axisLine={false} tickLine={false} />
            <Tooltip content={<Tip fmt={(v: number) => `${v}% of nights`} />} cursor={{ fill: "rgba(96,130,170,0.08)" }} />
            {bandNames.map(([k, name], i) => (
              <Bar key={k} dataKey={k} name={name} stackId="b" fill={BAND_COLOURS[i]} stroke={GAP} strokeWidth={2} isAnimationActive={anim} animationDuration={650} animationEasing="ease-out">
                {i === 0 && <LabelList dataKey={k} position="insideLeft" fill="#E9EEF4" fontSize={11} formatter={(v: number) => (v >= 12 ? `${v.toFixed(0)}%` : "")} />}
              </Bar>
            ))}
          </BarChart>
        </ResponsiveContainer></Chart>
        <p className="calloutText">
          Scheduling pays more often where the dark band is short. Spain's overnight record saves under 1% on{" "}
          {pct(es.bands.lt1, 0)} of nights, India's overnight window on {pct(inn.bands.lt1, 0)}, and India's daytime
          window on {pct(ind.bands.lt1, 0)}. Spain 2015-18 uses the corrected record (finding 17).
        </p>
        <TableTwin head={["Grid", "Nights", "Median", "Fleet total", "Under 1%", "1-5%", "5-20%", "Over 20%"]}
          rows={sv.map((s) => [s.label, s.nights, pct(s.median_pct), pct(s.fleet_pct), pct(s.bands.lt1, 0), pct(s.bands.b1_5, 0), pct(s.bands.b5_20, 0), pct(s.bands.gt20, 0)])} />
      </Panel>

      {/* ---------- 7 */}
      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">What was wrong, and what it is now</div>
            <div className="chartMeta">Every published number that changed. LESSONS.md records how each was caught.</div>
          </div>
        </div>
        <div className="tableWrap">
          <table className="runsTable">
            <thead><tr><th>Claim</th><th>First published</th><th>Now</th><th>Why it changed</th></tr></thead>
            <tbody>
              <tr><td>Hosting capacity at 250 kW</td><td>14.1×</td><td><strong>{H.median.toFixed(1)}×</strong></td><td>Synchronised arrivals, an overstated baseline, then one favourable fleet draw</td></tr>
              <tr><td>Spain median overnight saving</td><td>3.3%</td><td><strong>{pct(es.median_pct)}</strong></td><td>The input record was wrong on the first twelve days of every month</td></tr> {/* figures-ok: the first-published value is history */}
              <tr><td>Spain fleet-wide saving</td><td>10.4%</td><td><strong>{pct(es.fleet_pct)}</strong></td><td>Same</td></tr> {/* figures-ok: the first-published value is history */}
              <tr><td>India overnight median saving</td><td>0.05%</td><td><strong>{pct(inn.median_pct, 2)}</strong></td><td>A parser read the wrong fuel column on most days, and the night was not stitched across midnight</td></tr>
              <tr><td>Rolling control vs one-shot</td><td>238% worse</td><td><strong>{Math.abs(mpc.mpc_closes_gap_pct)}% worse</strong></td><td>The baseline had been reading true intensities, then the input record was corrected</td></tr>
              <tr><td>Synthetic carbon curve</td><td>"good enough"</td><td><strong>worse than nothing</strong></td><td>Its shape was roughly inverted</td></tr>
            </tbody>
          </table>
        </div>
      </Panel>

      {/* ---------- 2 */}
      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">How much grid does coordination buy?</div>
            <div className="chartMeta">Hosting-capacity gain on a 250 kW transformer across {H.draws.length} draws of the fleet</div>
          </div>
          <div className="legend">
            <span className="legendItem"><span className="legendSwatch" style={{ background: BLUE }} />Fleet draws</span>
            <span className="legendItem"><span className="legendSwatch" style={{ background: ORANGE }} />The draw first published ({H.published_first_draw.toFixed(1)}×)</span>
          </div>
        </div>
        <Chart height={220}><ResponsiveContainer width="100%" height="100%">
          <BarChart data={hist} margin={{ top: 8, right: 18, left: 0, bottom: 4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="bin" tick={{ fill: INK3, fontSize: 11 }} axisLine={{ stroke: GRID }} tickLine={false} />
            <YAxis allowDecimals={false} width={34} tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} />
            <Tooltip content={<Tip fmt={(v: number) => `${v} draw${v === 1 ? "" : "s"}`} />} cursor={{ fill: "rgba(96,130,170,0.08)" }} />
            <Bar dataKey="others" name="Other draws" stackId="h" fill={BLUE} stroke={GAP} strokeWidth={2} isAnimationActive={anim} animationDuration={650} animationEasing="ease-out" />
            <Bar dataKey="published" name="First published" stackId="h" fill={ORANGE} stroke={GAP} strokeWidth={2} radius={[4, 4, 0, 0]} isAnimationActive={anim} animationDuration={650} animationEasing="ease-out" />
          </BarChart>
        </ResponsiveContainer></Chart>
        <p className="calloutText">
          The first published draw, {H.published_first_draw.toFixed(1)}×, was the most favourable of the twenty. The median is{" "}
          <strong>{H.median.toFixed(1)}×</strong>. Most of the spread comes from how many cars charge-on-arrival can fit:
          coordination hosts {Math.min(...H.draws.map((d: any) => d.coordinated))} to {Math.max(...H.draws.map((d: any) => d.coordinated))} vehicles
          in every draw.
        </p>
        <div className="chartHeader" style={{ marginTop: 22 }}>
          <div>
            <div className="chartTitle">The gain falls as the transformer loosens</div>
            <div className="chartMeta">Range across draws, median marked · 6 draws per rating except 250 kW (20)</div>
          </div>
        </div>
        <Chart height={190}><ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={ratingData} margin={{ top: 8, right: 18, left: 0, bottom: 4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="rating" tick={{ fill: INK3, fontSize: 11 }} axisLine={{ stroke: GRID }} tickLine={false} />
            <YAxis domain={[0, 8]} width={34} tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v) => `${v}×`} />
            <Tooltip content={<Tip fmt={(v: number, p: any) => (p.dataKey === "median" ? `${v}×` : `${p.payload.base.toFixed(1)}-${(p.payload.base + p.payload.span).toFixed(1)}×`)} />} cursor={{ fill: "rgba(96,130,170,0.08)" }} />
            <Bar dataKey="base" stackId="r" fill="transparent" isAnimationActive={anim} animationDuration={650} animationEasing="ease-out" />
            <Bar dataKey="span" name="Range" stackId="r" fill={RANGE} radius={[4, 4, 4, 4]} isAnimationActive={anim} animationDuration={650} animationEasing="ease-out" />
            <Line dataKey="median" name="Median" stroke="none" dot={{ r: 5, fill: BLUE, stroke: GAP, strokeWidth: 2 }} activeDot={{ r: 6 }} isAnimationActive={anim} animationDuration={650} animationEasing="ease-out" />
          </ComposedChart>
        </ResponsiveContainer></Chart>
        <TableTwin head={["Rating", "On arrival", "Coordinated", "Median gain", "Min", "Max", "Draws"]}
          rows={H.ratings.map((r: any) => [`${r.rating_kw} kW`, r.dumb, r.coordinated, `${r.gain}×`, `${r.gain_min}×`, `${r.gain_max}×`, r.seeds])} />
      </Panel>

      {/* ---------- 3 */}
      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">Which assumptions move the hosting gain?</div>
            <div className="chartMeta">Each assumed input changed on its own · the shaded band is the spread from redrawing the same fleet</div>
          </div>
          <div className="legend">
            <span className="legendItem"><span className="legendSwatch" style={{ background: GREY }} />Inside the noise band</span>
            <span className="legendItem"><span className="legendSwatch" style={{ background: BLUE }} />Beyond it</span>
          </div>
        </div>
        <Chart height={Math.max(300, sens.length * 22 + 40)}><ResponsiveContainer width="100%" height="100%">
          <BarChart data={sens} layout="vertical" margin={{ top: 4, right: 36, left: 8, bottom: 4 }} barCategoryGap={4}>
            <CartesianGrid stroke={GRID} horizontal={false} />
            <XAxis type="number" domain={[0, 10]} ticks={[0, 2, 4, 6, 8, 10]} tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v) => `${v}×`} />
            <YAxis type="category" dataKey="label" width={narrow ? 128 : 230} tick={{ fill: INK2, fontSize: narrow ? 10 : 11 }} axisLine={false} tickLine={false} interval={0} />
            <Tooltip content={<Tip fmt={(v: number) => `${v}×`} />} cursor={{ fill: "rgba(96,130,170,0.08)" }} />
            <ReferenceArea x1={S.band[0]} x2={S.band[1]} fill={BLUE} fillOpacity={0.17} />
            <ReferenceLine x={S.median} stroke={INK2} strokeWidth={1} />
            <Bar dataKey="gain" name="Gain" radius={[0, 4, 4, 0]} isAnimationActive={anim} animationDuration={650} animationEasing="ease-out">
              {sens.map((r: any) => <Cell key={r.name} fill={r.outside_band ? BLUE : GREY} />)}
              <LabelList dataKey="gain" position="right" fill={INK2} fontSize={10} formatter={(v: number) => `${v.toFixed(1)}×`} />
            </Bar>
          </BarChart>
        </ResponsiveContainer></Chart>
        <p className="calloutText">
          A peakier baseline, more homes on the unit and faster chargers each lift the gain clearly past the noise band. Nothing lowers it.
          These runs test the sensitivity to my assumptions. A real feeder would test the assumptions themselves.
        </p>
        <TableTwin head={["Input changed", "Group", "Gain", "Beyond noise"]} rows={S.rows.map((r: any) => [r.what, r.group, `${r.gain}×`, r.outside_band ? "yes" : "no"])} />
      </Panel>

      {/* ---------- 4 */}
      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">How well can the next night be forecast?</div>
            <div className="chartMeta">Share of the achievable saving a forecast-driven schedule captures, scored on what happened</div>
          </div>
          <div className="legend">
            <span className="legendItem"><span className="legendSwatch" style={{ background: GREY }} />Lags and calendar only</span>
            <span className="legendItem"><span className="legendSwatch" style={{ background: BLUE }} />+ day-ahead solar, wind, load</span>
            <span className="legendItem"><span className="legendSwatch" style={{ background: AQUA }} />Deployed (adds day-ahead price)</span>
          </div>
        </div>
        <Chart height={250}><ResponsiveContainer width="100%" height="100%">
          <BarChart data={fcData} margin={{ top: 18, right: 18, left: 0, bottom: 4 }} barGap={4}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="grid" tick={{ fill: INK2, fontSize: 12 }} axisLine={{ stroke: GRID }} tickLine={false} />
            <YAxis domain={[0, 100]} width={40} tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v) => `${v}%`} />
            <Tooltip content={<Tip fmt={(v: number) => `${v}%`} />} cursor={{ fill: "rgba(96,130,170,0.08)" }} />
            <Bar dataKey="lags" name="Lags and calendar only" fill={GREY} radius={[4, 4, 0, 0]} isAnimationActive={anim} animationDuration={650} animationEasing="ease-out">
              <LabelList dataKey="lags" position="top" fill={INK2} fontSize={11} formatter={(v: number) => `${v.toFixed(0)}%`} />
            </Bar>
            <Bar dataKey="dayahead" name="+ day-ahead forecasts" fill={BLUE} radius={[4, 4, 0, 0]} isAnimationActive={anim} animationDuration={650} animationEasing="ease-out">
              <LabelList dataKey="dayahead" position="top" fill={INK2} fontSize={11} formatter={(v: number) => `${v.toFixed(0)}%`} />
            </Bar>
            <Bar dataKey="final" name="Deployed model" fill={AQUA} radius={[4, 4, 0, 0]} isAnimationActive={anim} animationDuration={650} animationEasing="ease-out">
              <LabelList dataKey="final" position="top" fill={INK2} fontSize={11} formatter={(v: number) => (v ? `${v.toFixed(0)}%` : "")} />
            </Bar>
          </BarChart>
        </ResponsiveContainer></Chart>
        <p className="calloutText">
          On the 2018 grid the day-ahead inputs add {Math.round(F.es2018.with_day_ahead - F.es2018.lags_only)} points. On today's grid they add{" "}
          {Math.round(F.es2025.with_day_ahead - F.es2025.lags_only)}, because solar has made the daily shape regular enough for lags to do much of the
          work. The forecast gate then cuts the nights that end worse than charging on arrival from {pct(F.es2025.deployed_worse, 0)} to{" "}
          {pct(F.es2025.deployed_gated_worse, 0)} on the 2025 grid.
        </p>
        <TableTwin head={["Grid", "Lags only", "+ day-ahead", "Deployed", "Worse nights", "With gate"]}
          rows={[
            ["Spain 2018 grid", pct(F.es2018.lags_only, 0), pct(F.es2018.with_day_ahead, 0), "-", "-", "-"],
            ["Spain 2025 grid", pct(F.es2025.lags_only, 0), pct(F.es2025.with_day_ahead, 0), pct(F.es2025.deployed, 0), pct(F.es2025.deployed_worse, 0), pct(F.es2025.deployed_gated_worse, 0)],
          ]} />
      </Panel>

      {/* ---------- 5 */}
      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">Does re-planning every hour beat planning once?</div>
            <div className="chartMeta">Mean regret against perfect foresight, % of the naive schedule's emissions · {C.nights} held-out nights · lower is better</div>
          </div>
        </div>
        <Chart height={ctrl.length * 34 + 40}><ResponsiveContainer width="100%" height="100%">
          <BarChart data={ctrl} layout="vertical" margin={{ top: 4, right: 40, left: 8, bottom: 4 }} barCategoryGap={6}>
            <CartesianGrid stroke={GRID} horizontal={false} />
            <XAxis type="number" tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v) => `${v}%`} />
            <YAxis type="category" dataKey="name" width={narrow ? 118 : 170} tick={{ fill: INK2, fontSize: 12 }} axisLine={false} tickLine={false} interval={0} />
            <Tooltip content={<Tip fmt={(v: number) => `${v.toFixed(2)}%`} />} cursor={{ fill: "rgba(96,130,170,0.08)" }} />
            <Bar dataKey="v" name="Regret" radius={[0, 4, 4, 0]} isAnimationActive={anim} animationDuration={650} animationEasing="ease-out">
              {ctrl.map((c) => <Cell key={c.name} fill={c.hl ? BLUE : GREY} />)}
              <LabelList dataKey="v" position="right" fill={INK2} fontSize={11} formatter={(v: number) => `${v.toFixed(2)}%`} />
            </Bar>
          </BarChart>
        </ResponsiveContainer></Chart>
        <p className="calloutText">
          The one-shot plan has the lowest regret. Re-solving every hour loses to it, and adding a penalty for waiting raises regret at every strength tried.
        </p>
        <TableTwin head={["Controller", "Mean regret"]} rows={ctrl.map((c) => [c.name, `${c.v.toFixed(3)}%`])} />
      </Panel>

      {/* ---------- 6 */}
      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">India: where there is a saving</div>
            <div className="chartMeta">Median carbon cut by charging window · {R.india.days} days of Grid-India 15-minute data · Spain overnight for scale</div>
          </div>
        </div>
        <Chart height={220}><ResponsiveContainer width="100%" height="100%">
          <BarChart data={inData} layout="vertical" margin={{ top: 4, right: 50, left: 8, bottom: 4 }} barCategoryGap={8}>
            <CartesianGrid stroke={GRID} horizontal={false} />
            <XAxis type="number" tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v) => `${v}%`} />
            <YAxis type="category" dataKey="name" width={narrow ? 100 : 130} tick={{ fill: INK2, fontSize: 12 }} axisLine={false} tickLine={false} />
            <Tooltip content={<Tip fmt={(v: number) => `${v.toFixed(2)}%`} />} cursor={{ fill: "rgba(96,130,170,0.08)" }} />
            <Bar dataKey="v" name="Median cut" radius={[0, 4, 4, 0]} isAnimationActive={anim} animationDuration={650} animationEasing="ease-out">
              {inData.map((c) => <Cell key={c.name} fill={c.hl ? BLUE : GREY} />)}
              <LabelList dataKey="v" position="right" fill={INK2} fontSize={11} formatter={(v: number) => `${v.toFixed(2)}%`} />
            </Bar>
          </BarChart>
        </ResponsiveContainer></Chart>
        <p className="calloutText">
          India's overnight window is the dirtiest and flattest part of its day, and it is the habit this project was built around. The
          daytime window is worth about {pct(ind.median_pct, 1)}. The afternoon window has the widest swing but saves nothing: the fleet
          needs nearly all of those hours to charge.
        </p>
        <TableTwin head={["Window", "Mean intensity", "Spread", "Median cut", "Nights under 1%"]}
          rows={["overnight", "daytime", "afternoon"].map((k) => [k, `${W[k].mean_window_ci} g`, `${W[k].window_spread_pct}%`, `${W[k].median_cut_pct}%`, `${W[k].under_1pct}%`])} />
      </Panel>

      <p className="provenance">
        Built by <code>ml/export_results.py</code> · {new Date(R.generated_at).toISOString().slice(0, 10)}
      </p>
    </>
  );
}
