import {
  BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, LabelList,
} from "recharts";
import { Check, X, Minus } from "lucide-react";
import evidence from "./data/evidence.json";

const OPT = "#3987e5";
const NEG = "#d03b3b";
const GRID = "#202A36";
const INK3 = "#5F6C7B";

type Verdict = "yes" | "no" | "na";

/** Identity is never colour-alone: every verdict ships an icon and its text. */
function Mark({ v }: { v: Verdict }) {
  if (v === "yes") return <Check size={13} className="vYes" strokeWidth={2.6} />;
  if (v === "no") return <X size={13} className="vNo" strokeWidth={2.6} />;
  return <Minus size={13} className="vNa" strokeWidth={2.6} />;
}

type Row = { dim: string; naive: [Verdict, string]; synth: [Verdict, string]; grid: [Verdict, string] };

const ROWS: Row[] = [
  {
    dim: "Carbon data",
    naive: ["na", "none — ignores the grid"],
    synth: ["no", "hand-tuned Gaussian"],
    grid: ["yes", "measured ENTSO-E mix × IPCC AR5"],
  },
  {
    dim: "Price data",
    naive: ["na", "none"],
    synth: ["no", "assumed 3-step tariff"],
    grid: ["yes", "day-ahead market + PVPC access"],
  },
  {
    dim: "Respects the street transformer",
    naive: ["no", "overloads it by 463 kW"],
    synth: ["no", "constraint never reachable"],
    grid: ["yes", "hard constraint in the LP"],
  },
  {
    dim: "Needs a solver at all",
    naive: ["na", "no scheduling"],
    synth: ["no", "greedy matches it exactly"],
    grid: ["yes", "only under a coupling limit"],
  },
  {
    dim: "Reports when it makes things worse",
    naive: ["na", "—"],
    synth: ["no", "single flattering number"],
    grid: ["yes", "increases shown, not hidden"],
  },
  {
    dim: "Validated against measured outcomes",
    naive: ["na", "—"],
    synth: ["no", "never backtested"],
    grid: ["yes", `${evidence.savings.nights.toLocaleString()}-night backtest`],
  },
];

function RegretTip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="tip">
      <div className="tipHour">{d.model}</div>
      <div className="tipRow">Achievable saving captured<b>{d.captured_pct}%</b></div>
      {d.mae != null && <div className="tipRow">Forecast error (MAE)<b>{d.mae.toFixed(1)}</b></div>}
      <div className="tipRow">CO₂ vs perfect foresight<b>{Math.round(d.captured_kg)} kg</b></div>
    </div>
  );
}

function BinTip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="tip">
      <div className="tipHour">{d.label} saving</div>
      <div className="tipRow">Nights<b>{d.nights}</b></div>
      <div className="tipRow">Share of the year<b>{d.share_pct}%</b></div>
    </div>
  );
}

export default function Comparison() {
  const s = evidence.savings;
  const forecast = evidence.forecast;
  const coupling = evidence.coupling;

  return (
    <>
      <section className="card">
        <div className="chartHeader">
          <div>
            <div className="chartTitle">How this differs from the usual approach</div>
            <div className="chartMeta">
              Two things it is measured against: charging the moment you get home, and an
              optimizer driven by a plausible-looking synthetic curve
            </div>
          </div>
        </div>
        <div className="matrixWrap">
          <table className="matrix">
            <thead>
              <tr>
                <th />
                <th>Charging on arrival</th>
                <th>Synthetic-curve optimizer</th>
                <th className="mine">GridSense</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((r) => (
                <tr key={r.dim}>
                  <th scope="row">{r.dim}</th>
                  {([r.naive, r.synth, r.grid] as [Verdict, string][]).map(([v, txt], i) => (
                    <td key={i} className={i === 2 ? "mine" : ""}>
                      <Mark v={v} /> <span>{txt}</span>
                    </td>
                  ))}
                </tr>
              ))}
              <tr className="matrixTotal">
                <th scope="row">CO₂ saved vs charging on arrival</th>
                <td>0% — the baseline</td>
                <td>
                  <span className="claimBad">claims 32.4%</span>
                  <span className="claimNote">measured: worse than doing nothing</span>
                </td>
                <td className="mine">
                  <span className="claimGood">{s.median_pct}% median · {s.fleet_total_pct}% fleet total</span>
                  <span className="claimNote">across {s.nights.toLocaleString()} measured nights</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <div className="chartHeader">
          <div>
            <div className="chartTitle">Does the forecast pick the right hours?</div>
            <div className="chartMeta">
              % of the achievable CO₂ saving each method captures · scheduled on the forecast,
              scored against what actually happened, compared to perfect foresight
            </div>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={230}>
          <BarChart data={forecast} layout="vertical" margin={{ top: 4, right: 56, left: 8, bottom: 4 }}>
            <CartesianGrid stroke={GRID} horizontal={false} />
            <XAxis type="number" domain={[-40, 80]} tick={{ fill: INK3, fontSize: 11 }}
              axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}%`} />
            <YAxis type="category" dataKey="model" width={148} tick={{ fill: INK3, fontSize: 11 }}
              axisLine={false} tickLine={false} />
            <Tooltip content={<RegretTip />} cursor={{ fill: "rgba(255,255,255,.03)" }} />
            <ReferenceLine x={0} stroke="#4A5563" strokeWidth={1} />
            <Bar dataKey="captured_pct" radius={[0, 4, 4, 0]} barSize={18} isAnimationActive={false}>
              {forecast.map((r: any) => (
                <Cell key={r.model} fill={r.captured_pct < 0 ? NEG : OPT} />
              ))}
              <LabelList dataKey="captured_pct" position="right"
                formatter={(v: number) => `${v.toFixed(1)}%`}
                style={{ fill: "#9AA7B6", fontSize: 11 }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <p className="calloutText">
          The synthetic curve scores <strong className="negText">negative</strong>. Scheduling
          against it is worse than not optimising at all — it steers charging into hours it
          believes are clean and the real grid does not. Every honest method beats it, and a
          ridge regression on day-ahead forecasts captures{" "}
          <strong>{forecast[forecast.length - 1].captured_pct}%</strong> of what perfect
          foresight would.
        </p>
      </section>

      <section className="card">
        <div className="chartHeader">
          <div>
            <div className="chartTitle">The saving is long-tailed, not flat</div>
            <div className="chartMeta">
              {s.nights.toLocaleString()} measured overnight windows · median {s.median_pct}% ·
              90th percentile {s.p90_pct}% · best night {s.max_pct}%
            </div>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={210}>
          <BarChart data={s.bins} margin={{ top: 14, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="label" tick={{ fill: INK3, fontSize: 11 }}
              axisLine={{ stroke: GRID }} tickLine={false} />
            <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false}
              width={44} label={undefined} />
            <Tooltip content={<BinTip />} cursor={{ fill: "rgba(255,255,255,.03)" }} />
            <Bar dataKey="nights" fill={OPT} radius={[4, 4, 0, 0]} isAnimationActive={false}>
              <LabelList dataKey="share_pct" position="top"
                formatter={(v: number) => `${v}%`}
                style={{ fill: "#9AA7B6", fontSize: 11 }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <p className="calloutText">
          <strong>{s.under_1pct_share}% of nights save under 1%</strong> — on those the grid is
          flat enough that moving the charge achieves nothing. Another{" "}
          <strong>{s.over_20pct_share}%</strong> save over 20%. A single headline percentage
          hides both facts, which is why this project reports the distribution instead.
        </p>
      </section>

      <section className="card">
        <div className="chartHeader">
          <div>
            <div className="chartTitle">When does the optimiser actually earn its keep?</div>
            <div className="chartMeta">
              Linear program vs a greedy per-vehicle fill, recomputed on every build
            </div>
          </div>
        </div>
        <div className="matrixWrap">
          <table className="matrix">
            <thead>
              <tr>
                <th>Scenario</th>
                <th>Objective gap, LP vs greedy</th>
                <th>Greedy peak</th>
                <th>Verdict</th>
              </tr>
            </thead>
            <tbody>
              {coupling.map((c: any) => (
                <tr key={c.case}>
                  <th scope="row">{c.case}</th>
                  <td>{c.objective_gap_pct === 0 ? "0.0000%" : `${c.objective_gap_pct}%`}</td>
                  <td>
                    {c.greedy_peak_kw} kW
                    {c.feeder_kw && <span className="claimNote">limit {c.feeder_kw} kW</span>}
                  </td>
                  <td className={c.greedy_violates ? "mine" : ""}>
                    {c.greedy_violates ? (
                      <><Check size={13} className="vYes" strokeWidth={2.6} /> <span>solver required</span></>
                    ) : (
                      <><X size={13} className="vNo" strokeWidth={2.6} /> <span>greedy is already optimal</span></>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="calloutText">
          Without a constraint linking vehicles the problem <em>separates</em> — each car fills
          its own cleanest hours and a ten-line greedy loop matches the LP exactly. Vehicle
          variety does not change that, which was the surprise. Only a shared limit makes the
          schedule a real optimisation: greedy breaches a 180 kW transformer by{" "}
          <strong>{coupling[2].greedy_over_limit_kw} kW</strong>,
          while the LP lands on it exactly.
        </p>
      </section>

      <p className="provenance">
        Generated from {evidence.source} · rebuilt by <code>ml/export_evidence.py</code>
        {evidence.git_rev ? ` at ${evidence.git_rev}` : ""} ·{" "}
        {new Date(evidence.generated_at).toISOString().slice(0, 10)}
      </p>
    </>
  );
}
