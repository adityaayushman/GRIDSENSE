import { useMemo, useState } from "react";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ReferenceLine, LabelList, Cell,
} from "recharts";
import data from "./data/validation.json";
import Segmented from "./Segmented";
import { usePrefersReduced, useReveal } from "./motion";

const MODEL = "#8C8576";   // the modelled baseline: neutral, it is the thing being checked
const REAL = "#3987e5";    // measured
const COORD = "#3987e5";
const DUMB = "#d95926";
const GRID = "#2C2823";
const INK3 = "#8C8576";

type Region = (typeof data.regions)[number];
type Key = "spain" | "uk" | "india" | "compare";

const hh = (h: number) => `${String(h).padStart(2, "0")}:00`;
const kw = (n: number) => `${n.toFixed(2)} kW`;

function Panel({ children }: { children: React.ReactNode }) {
  const reduced = usePrefersReduced();
  const { ref, shown } = useReveal<HTMLElement>(reduced);
  return <section ref={ref} className={`card reveal ${shown ? "isIn" : ""}`}>{children}</section>;
}

function Head({ title, meta }: { title: string; meta: string }) {
  return (
    <div className="chartHeader">
      <div>
        <div className="chartTitle">{title}</div>
        <div className="chartMeta">{meta}</div>
      </div>
    </div>
  );
}

function Tip({ active, payload, label, unit = "kW" }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tip">
      <div className="tipHour">{label}</div>
      {payload.map((p: any) => (
        <div className="tipRow" key={p.dataKey}>
          <span className="legendSwatch" style={{ background: p.stroke ?? p.fill }} />
          {p.name}<b>{Number(p.value).toFixed(2)} {unit}</b>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- a raw-data region (Spain, UK)
function RawRegion({ r }: { r: Region & { baseline: any; hosting: any } }) {
  const reduced = usePrefersReduced();
  const homes = r.street_homes;
  const s = r.baseline.stats;
  const m = r.baseline.model;
  const h = r.hosting;

  const profile = useMemo(() => Array.from({ length: 24 }, (_, i) => ({
    hour: hh(i),
    real: r.baseline.profiles.real_winter[i] / homes,
    annual: r.baseline.profiles.real_annual[i] / homes,
    model: r.baseline.profiles.model[i] / homes,
  })), [r, homes]);

  const bars = useMemo(() => [
    { name: "Model baseline", dumb: h.model.dumb, coord: h.model.coordinated, gain: h.model.gain, real: false },
    ...(["p10", "median", "p90"] as const).map((st) => {
      const row = h.rows.find((x: any) => x.street === st && x.form === "winter");
      return { name: `Real street, ${st === "median" ? "median" : st} winter`, dumb: row.dumb, coord: row.coordinated, gain: row.gain, real: true };
    }),
  ], [h]);

  const [lo, hi] = h.winter_gain_range;
  const rel = h.median_street.gain / h.model.gain;
  const verdict = rel < 0.85
    ? `On real streets the gain is lower than the model's (${h.median_street.gain}× against ${h.model.gain}×), so the headline was optimistic here.`
    : rel <= 1.15
      ? `The gain on real streets (${h.median_street.gain}× at the median) matches the model's ${h.model.gain}× within its own noise band of ${h.model.noise_band[0]}–${h.model.noise_band[1]}×. The shape was wrong; the headline holds.`
      : `The gain on real streets is higher than the model's (${h.median_street.gain}× at the median against ${h.model.gain}×): a peak that coincides with arriving cars leaves charge-on-arrival little room, so coordination is worth more.`;
  return (
    <>
      <section className="hero">
        <div className="heroMain">
          <div className="eyebrow">{r.name} · {r.homes_in_panel.toLocaleString()} real homes</div>
          <div className="heroValue" style={{ color: REAL }}>{lo.toFixed(1)}–{hi.toFixed(1)}×</div>
          <div className="heroLabel">hosting-capacity gain on real winter streets</div>
          <div className="heroSub">the modelled baseline gave {h.model.gain}× on the same method</div>
        </div>
        <div className="heroNote">
          Real homes in this panel peak at <strong>{hh(s.peak_hour_winter_mode)}</strong>, about{" "}
          <strong>{kw(s.peak_kw_per_home_winter.median)}</strong> a home; the modelled baseline peaks at {hh(m.peak_hour)} at{" "}
          {kw(m.peak_kw_per_home)}. {verdict}
        </div>
      </section>

      <Panel>
        <Head title="A real street against the model, per home"
          meta={`Mean day, kW per home · street of ${homes} homes · ${r.source}`} />
        <div className="legend" style={{ marginBottom: 6 }}>
          <span className="legendItem"><span className="legendSwatch" style={{ background: REAL }} />Real, winter</span>
          <span className="legendItem"><span className="legendSwatch" style={{ background: "#7fb4f5" }} />Real, whole year</span>
          <span className="legendItem"><span className="legendSwatch" style={{ background: MODEL }} />Modelled baseline</span>
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={profile} margin={{ top: 8, right: 20, left: 0, bottom: 4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="hour" interval={2} tick={{ fill: INK3, fontSize: 11 }} axisLine={{ stroke: GRID }} tickLine={false} />
            <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} width={44}
              domain={[0, "auto"]} tickCount={5} tickFormatter={(v: number) => v.toFixed(1)} />
            <Tooltip content={<Tip />} cursor={{ stroke: GRID }} />
            <ReferenceLine x="18:00" stroke={INK3} strokeDasharray="3 3"
              label={{ value: "cars arrive", position: "insideTopLeft", fill: INK3, fontSize: 10 }} />
            <Line type="monotone" dataKey="real" name="Real, winter" stroke={REAL} strokeWidth={2.5} dot={false} isAnimationActive={!reduced} />
            <Line type="monotone" dataKey="annual" name="Real, whole year" stroke="#7fb4f5" strokeWidth={1.75} dot={false} strokeDasharray="2 3" isAnimationActive={!reduced} />
            <Line type="monotone" dataKey="model" name="Modelled baseline" stroke={MODEL} strokeWidth={2.25} dot={false} strokeDasharray="6 3" isAnimationActive={!reduced} />
          </LineChart>
        </ResponsiveContainer>
        <p className="calloutText">
          Peak-to-trough of the real average day is <strong>{s.peak_to_trough_annual.median}</strong>, against{" "}
          <strong>{m.peak_to_trough}</strong> for the model. Between random streets of {homes} homes the winter peak
          varies only from {kw(s.peak_kw_per_home_winter.p5)} to {kw(s.peak_kw_per_home_winter.p95)} a home, so
          which street you pick matters little; the <em>shape</em> is what the model got wrong.
        </p>
      </Panel>

      <Panel>
        <Head title="Vehicles one 250 kW unit can host"
          meta="Charging on arrival against coordinated · same fleet, same method, only the baseline changes" />
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={bars} margin={{ top: 22, right: 16, left: 0, bottom: 4 }} barGap={4}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="name" tick={{ fill: INK3, fontSize: 10.5 }} axisLine={{ stroke: GRID }} tickLine={false} interval={0} />
            <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} width={44} />
            <Tooltip content={<Tip unit="EVs" />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
            <Legend wrapperStyle={{ fontSize: 11, color: INK3 }} />
            <Bar dataKey="dumb" name="Charge on arrival" fill={DUMB} radius={[2, 2, 0, 0]} isAnimationActive={!reduced} />
            <Bar dataKey="coord" name="Coordinated" fill={COORD} radius={[2, 2, 0, 0]} isAnimationActive={!reduced}>
              <LabelList dataKey="gain" position="top" formatter={(v: number) => `${v.toFixed(1)}×`} style={{ fill: INK3, fontSize: 11 }} />
              {bars.map((b) => <Cell key={b.name} fill={b.real ? COORD : "#5a7fae"} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <details className="tableTwin">
          <summary>Table view</summary>
          <div className="tableWrap">
            <table className="runsTable">
              <thead><tr><th>Street</th><th>Peak/home</th><th>Peak hour</th><th>On arrival</th><th>Coordinated</th><th>Gain</th></tr></thead>
              <tbody>
                <tr><td>Model baseline</td><td>{kw(m.peak_kw_per_home)}</td><td>{hh(m.peak_hour)}</td><td>{h.model.dumb}</td><td>{h.model.coordinated}</td><td>{h.model.gain}×</td></tr>
                {h.rows.map((x: any) => (
                  <tr key={x.key}><td>Real {x.street}, {x.form}</td><td>{kw(x.peak_kw_per_home)}</td><td>{hh(x.peak_hour)}</td><td>{x.dumb}</td><td>{x.coordinated}</td><td>{x.gain}×</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
        <p className="calloutText">
          The model's own noise band (twenty fleet draws) is {h.model.noise_band[0]}–{h.model.noise_band[1]}×, median{" "}
          {h.model.noise_median}×; the {h.model.gain}× shown is draw zero, the same fleet used on the real streets. Charge-on-arrival
          ceilings here are small because real evening demand is already close to the rating when the cars arrive.
        </p>
      </Panel>

      <p className="provenance">
        {r.source} · {r.licence} · <code>ml/validation/</code> · streets of {homes} homes sampled 300 times from the panel
      </p>
    </>
  );
}

// ---------------------------------------------------------------- India: a published figure, not raw data
function IndiaRegion({ r }: { r: any }) {
  const reduced = usePrefersReduced();
  const rows = r.hosting.rows as any[];
  const [lo, hi] = r.hosting.published_gain_range;
  const synth = (r.synthetic ?? []) as any[];
  const byLabel = (k: string, sc: string) => synth.find((x) => x.shape_source === k && x.scaling === sc);
  const synthProfile = Array.from({ length: 24 }, (_, i) => ({
    hour: hh(i),
    model: r.model_profile_225_kw[i] / r.street_homes,
    spain: byLabel("spain", "Pune peak 225 W")?.profile_kw[i] / r.street_homes,
    uk: byLabel("uk", "Pune peak 225 W")?.profile_kw[i] / r.street_homes,
  }));
  const bars = rows.map((x) => ({ name: x.label.replace("Scaled to Pune published ", "Pune ").replace(" (Delhi consumption)", ""), dumb: x.dumb, coord: x.coordinated, gain: x.gain }));
  return (
    <>
      <section className="hero">
        <div className="heroMain">
          <div className="eyebrow">India · a published-figure check, not raw data</div>
          <div className="heroValue" style={{ color: REAL }}>{lo.toFixed(1)}–{hi.toFixed(1)}×</div>
          <div className="heroLabel">gain on a 100 kVA unit with the baseline set to Pune's published peak</div>
          <div className="heroSub">the model gave {r.hosting.model.gain}× with its Delhi-based baseline</div>
        </div>
        <div className="heroNote">
          India has <strong>no open household smart-meter data</strong>. Prayas Energy Group meters 115 households
          but publishes only summaries; the one figure that bears on a transformer is Pune City's evening peak of{" "}
          <strong>200–250 W a household</strong> around {hh(r.published.peak_hour)}. Setting the baseline to that, below the
          model's 384 W, lifts the number of EVs the unit hosts (from {r.hosting.model.dumb} to about {rows[2].dumb} on arrival)
          and leaves the <strong>gain</strong> at {lo.toFixed(1)}–{hi.toFixed(1)}×. Weaker evidence than a meter panel, and
          Pune is not Delhi.
        </div>
      </section>

      <Panel>
        <Head title="Vehicles a 100 kVA unit can host" meta={`${r.street_homes} homes · Indian fleet mix (57% two-wheelers, 35% three-wheelers, 8% cars)`} />
        <ResponsiveContainer width="100%" height={270}>
          <BarChart data={bars} margin={{ top: 22, right: 16, left: 0, bottom: 4 }} barGap={4}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="name" tick={{ fill: INK3, fontSize: 10.5 }} axisLine={{ stroke: GRID }} tickLine={false} interval={0} />
            <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} width={44} />
            <Tooltip content={<Tip unit="EVs" />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
            <Legend wrapperStyle={{ fontSize: 11, color: INK3 }} />
            <Bar dataKey="dumb" name="Charge on arrival" fill={DUMB} radius={[2, 2, 0, 0]} isAnimationActive={!reduced} />
            <Bar dataKey="coord" name="Coordinated" fill={COORD} radius={[2, 2, 0, 0]} isAnimationActive={!reduced}>
              <LabelList dataKey="gain" position="top" formatter={(v: number) => `${v.toFixed(1)}×`} style={{ fill: INK3, fontSize: 11 }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <p className="calloutText">
          What would validate India properly: household or feeder smart-meter data for a city whose consumption
          resembles the model's. Prayas's eMARC project is the closest, and its raw data is not public; asking them
          is the realistic next step. Until then India stays a modelled result with this one cross-check.
        </p>
      </Panel>
      <Panel>
        <Head title="Predicted Indian baselines, from real household shapes"
          meta="Synthetic: real Spanish and UK evening-peaking profiles rescaled to Indian demand · not validation" />
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={synthProfile} margin={{ top: 8, right: 20, left: 0, bottom: 4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="hour" interval={2} tick={{ fill: INK3, fontSize: 11 }} axisLine={{ stroke: GRID }} tickLine={false} />
            <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} width={44}
              domain={[0, "auto"]} tickCount={5} tickFormatter={(v: number) => v.toFixed(2)} />
            <Tooltip content={<Tip />} cursor={{ stroke: GRID }} />
            <Legend wrapperStyle={{ fontSize: 11, color: INK3 }} />
            <Line type="monotone" dataKey="model" name="Model shape" stroke={MODEL} strokeWidth={2.25} dot={false} strokeDasharray="6 3" isAnimationActive={!reduced} />
            <Line type="monotone" dataKey="spain" name="Spanish real shape" stroke={REAL} strokeWidth={2.25} dot={false} isAnimationActive={!reduced} />
            <Line type="monotone" dataKey="uk" name="UK real shape" stroke="#7fb4f5" strokeWidth={2.25} dot={false} strokeDasharray="2 3" isAnimationActive={!reduced} />
          </LineChart>
        </ResponsiveContainer>
        <div className="matrixWrap">
          <table className="matrix">
            <thead><tr><th /><th>Peak per home</th><th>On arrival</th><th>Coordinated</th><th className="mine">Gain</th></tr></thead>
            <tbody>
              {synth.map((x: any) => (
                <tr key={x.label}>
                  <th scope="row">{x.label}</th>
                  <td>{kw(x.peak_kw_per_home)} at {hh(x.peak_hour)}</td>
                  <td>{x.dumb}</td><td>{x.coordinated}</td>
                  <td className="mine">{x.dumb < 10 ? "n/m" : `${x.gain}×`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="calloutText">
          At Pune's published level, evening-peaking shapes give <strong>3.5–3.7×</strong>, so the gain is robust to shape. At
          Delhi's higher consumption they leave the unit almost full when cars arrive (5 EVs on arrival for the UK shape), and
          the ratio explodes to a number that is mostly a tiny denominator, marked n/m. What is stable is the{" "}
          <strong>coordinated</strong> capacity, 115–219 vehicles. These are predictions from borrowed shapes: they show
          what India might look like, and cannot confirm it.
        </p>
      </Panel>
      <p className="provenance">
        <a href={r.url} target="_blank" rel="noreferrer">{r.source}</a> · <code>ml/validation/india.py</code>
      </p>
    </>
  );
}

// ---------------------------------------------------------------- the comparison
function Compare() {
  const reduced = usePrefersReduced();
  const rows = data.comparison as any[];
  const bars = rows.map((c) => ({ name: c.name.replace(" (Basque Country and Navarre)", ""), model: c.model_gain, real: c.real_gain, kind: c.kind }));
  const gains = rows.map((c) => c.real_gain);
  return (
    <>
      <section className="hero">
        <div className="heroMain">
          <div className="eyebrow">Spain · UK · India, side by side</div>
          <div className="heroValue" style={{ color: REAL }}>{Math.min(...gains).toFixed(1)}–{Math.max(...gains).toFixed(1)}×</div>
          <div className="heroLabel">gain from coordination once the baseline is real</div>
          <div className="heroSub">the model's was {rows[0].model_gain}× (Europe) and {rows[2].model_gain}× (India)</div>
        </div>
        <div className="heroNote">
          Two regions are validated on <strong>raw household data</strong> and one on a <strong>published figure</strong>.
          The direction agrees everywhere: coordination hosts several times more vehicles than charging on arrival.
          Spain's real streets give about the model's gain, India's published figure leaves it near the model's, and the UK,
          whose homes peak at 19:00 as the cars arrive, shows a much larger one. The ratio holds up better than the absolute
          number of vehicles a transformer hosts, which moves with each region's demand.
        </div>
      </section>

      <Panel>
        <Head title="Hosting-capacity gain: model against real" meta="Median real street (winter) for Spain and the UK; Pune's published peak for India" />
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={bars} margin={{ top: 22, right: 16, left: 0, bottom: 4 }} barGap={6}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="name" tick={{ fill: INK3, fontSize: 11 }} axisLine={{ stroke: GRID }} tickLine={false} />
            <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} width={44} tickFormatter={(v: number) => `${v}×`} />
            <Tooltip content={<Tip unit="×" />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
            <Legend wrapperStyle={{ fontSize: 11, color: INK3 }} />
            <Bar dataKey="model" name="Modelled baseline" fill={MODEL} radius={[2, 2, 0, 0]} isAnimationActive={!reduced} />
            <Bar dataKey="real" name="Real data" fill={REAL} radius={[2, 2, 0, 0]} isAnimationActive={!reduced}>
              <LabelList dataKey="real" position="top" formatter={(v: number) => `${v.toFixed(1)}×`} style={{ fill: INK3, fontSize: 11 }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </Panel>

      <Panel>
        <Head title="What each region's data says" meta="Peak demand per home at the evening peak, model against real" />
        <div className="matrixWrap">
          <table className="matrix">
            <thead>
              <tr><th /><th>Evidence</th><th>Model peak</th><th>Real peak</th><th>On arrival</th><th>Coordinated</th><th className="mine">Gain</th></tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.key}>
                  <th scope="row">{c.name.replace(" (Basque Country and Navarre)", "")}</th>
                  <td>{c.kind === "raw" ? "raw panel" : "published figure"}</td>
                  <td>{kw(c.model_peak_kw_per_home)} at {hh(c.model_peak_hour)}</td>
                  <td>{kw(c.real_peak_kw_per_home)} at {hh(c.real_peak_hour)}</td>
                  <td>{c.model_dumb} → {c.real_dumb}</td>
                  <td>{c.model_coordinated} → {c.real_coordinated}</td>
                  <td className="mine">{c.model_gain}× → {c.real_gain}×</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="calloutText">
          Each region keeps its own fleet and transformer: 250 kW and the European fleet for Spain and the UK, 100 kVA
          and the Indian two- and three-wheeler mix for India. Spain and the UK are not like-for-like with India;
          compare the model with the real figure within a row, not down a column.
        </p>
      </Panel>
    </>
  );
}

export default function Validation() {
  const [key, setKey] = useState<Key>("spain");
  const spain = data.regions.find((r) => r.key === "spain") as any;
  const uk = data.regions.find((r) => r.key === "uk") as any;
  const india = data.regions.find((r) => r.key === "india") as any;
  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 14 }}>
        <div className="eyebrow">Validation against real data</div>
        <Segmented<Key> value={key} onChange={setKey}
          options={[
            { key: "spain", label: "Spain" },
            { key: "uk", label: "UK (others)" },
            { key: "india", label: "India" },
            { key: "compare", label: "Compare" },
          ]} />
      </div>
      {key === "spain" && <RawRegion r={spain} />}
      {key === "uk" && <RawRegion r={uk} />}
      {key === "india" && <IndiaRegion r={india} />}
      {key === "compare" && <Compare />}
    </>
  );
}
