import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, LabelList,
} from "recharts";
import robustness from "./data/india_robustness.json";
import intraday from "./data/india_robustness_intraday.json";
import { usePrefersReduced, useReveal } from "./motion";

const OK = "#3987e5";
const BAD = "#d95926";
const GRID = "#2C2823";
const INK3 = "#8C8576";

const R = robustness;
const TARGET_PCT = Math.round(R.target_overload_prob * 100);
const MARGINS = Object.keys(R.capacity_by_margin);

const capRows = MARGINS.map((m) => ({
  margin: Number(m),
  capacity: R.capacity_by_margin[m as keyof typeof R.capacity_by_margin] as number,
}));

const REPS = [
  { sigma: 3, key: "s3", name: "3% — the national forecast's own error", color: OK },
  { sigma: 20, key: "s20", name: "20% — a guessed feeder-level error", color: BAD },
];
const probRows = MARGINS.map((m) => {
  const row: Record<string, number> = { margin: Number(m) };
  for (const rep of REPS) {
    const r = R.rows.find((x) => x.error_sd_pct === rep.sigma);
    const p = r?.overload_prob_by_margin[m as keyof typeof r.overload_prob_by_margin] as number | undefined;
    row[rep.key] = p !== undefined ? Math.round(p * 1000) / 10 : 0;
  }
  return row;
});

const national = R.rows.find((r) => r.error_sd_pct === 3)!;
let bestMargin = MARGINS[0];
let bestProb = 1;
for (const m of MARGINS) {
  const p = national.overload_prob_by_margin[m as keyof typeof national.overload_prob_by_margin] as number;
  if (p < bestProb) { bestProb = p; bestMargin = m; }
}
const bestCapacity = R.capacity_by_margin[bestMargin as keyof typeof R.capacity_by_margin] as number;

const M = intraday;
const natlRolling = M.rows.filter((r) => r.error_sd_pct === 3 && r.margin_pct > 0);
const rollingRows = natlRolling.map((r) => ({
  margin: r.margin_pct,
  static: Math.round(r.static_overload_prob * 1000) / 10,
  rolling: Math.round(r.rolling_overload_prob * 1000) / 10,
}));
const nonzero = M.rows.filter((r) => r.error_sd_pct > 0);
const meanDiffPp = nonzero.reduce((a, r) => a + (r.rolling_overload_prob - r.static_overload_prob), 0)
  / nonzero.length * 100;
const worstRow = nonzero.reduce((a, r) => {
  const d = r.rolling_overload_prob - r.static_overload_prob;
  return d > (a.rolling_overload_prob - a.static_overload_prob) ? r : a;
}, nonzero[0]);

function CapTip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tip">
      <div className="tipHour">{label}% of the rating held back</div>
      <div className="tipRow">
        <span className="legendSwatch" style={{ background: OK }} />
        Capacity<b>{payload[0].value} vehicles</b>
      </div>
    </div>
  );
}

function ProbTip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tip">
      <div className="tipHour">{label}% of the rating held back</div>
      {payload.map((p: any) => (
        <div className="tipRow" key={p.dataKey}>
          <span className="legendSwatch" style={{ background: p.stroke }} />
          {p.name}<b>{p.value}% of draws overload</b>
        </div>
      ))}
    </div>
  );
}

function RollTip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tip">
      <div className="tipHour">{label}% margin held back</div>
      {payload.map((p: any) => (
        <div className="tipRow" key={p.dataKey}>
          <span className="legendSwatch" style={{ background: p.fill }} />
          {p.name}<b>{p.value}% of draws overload</b>
        </div>
      ))}
    </div>
  );
}

/** Finding 10's hosting-capacity gain assumed a perfect forecast of the street's other demand. This prices the gap. */
export default function IndiaRobustness() {
  const reduced = usePrefersReduced();
  const { ref, shown } = useReveal<HTMLElement>(reduced);

  return (
    <section ref={ref} className={`card reveal ${shown ? "isIn" : ""}`}>
      <div className="chartHeader">
        <div>
          <div className="chartTitle">
            Finding 10's {R.perfect_forecast_capacity} vehicles assumes a perfect forecast of the street
          </div>
          <div className="chartMeta">
            {R.rating_kva} kVA · {R.homes} homes · {R.draws} draws per error level · scheduled against a
            forecast of the other demand, scored against what the transformer actually carries
          </div>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={capRows} margin={{ top: 18, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="margin" tick={{ fill: INK3, fontSize: 11 }} axisLine={{ stroke: GRID }} tickLine={false}
            tickFormatter={(v: number) => `${v}%`}
            label={{ value: "margin held back from the rating", position: "insideBottom", offset: -2, fill: INK3, fontSize: 11 }} />
          <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} width={40} />
          <Tooltip content={<CapTip />} cursor={{ fill: "rgba(255,255,255,.03)" }} />
          <ReferenceLine y={R.dumb} stroke={BAD} strokeDasharray="4 4"
            label={{ value: `charging on arrival, ${R.dumb}`, position: "insideTopRight", fill: INK3, fontSize: 10 }} />
          <Bar dataKey="capacity" name="Coordinated, perfect forecast" fill={OK} radius={[3, 3, 0, 0]} isAnimationActive={!reduced}>
            <LabelList dataKey="capacity" position="top" style={{ fill: INK3, fontSize: 11 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="calloutText">
        Holding back margin to absorb forecast error is expensive by itself: at a 30% margin, capacity has
        already fallen from {R.perfect_forecast_capacity} to {R.capacity_by_margin["30"]} — barely above the{" "}
        {R.dumb} vehicles charging on arrival hosts with no coordination at all, and this bar still assumes the
        forecast is exactly right.
      </p>

      <div className="chartHeader">
        <div>
          <div className="chartTitle">No margin tested brings the real risk under {TARGET_PCT}%</div>
          <div className="chartMeta">
            Share of {R.draws} draws where the true load exceeds the rating, hour-to-hour error correlation{" "}
            {R.error_correlation}
          </div>
        </div>
        <div className="legend">
          {REPS.map((r) => (
            <span className="legendItem" key={r.key}>
              <span className="legendSwatch" style={{ background: r.color }} />{r.name}
            </span>
          ))}
        </div>
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={probRows} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="margin" tick={{ fill: INK3, fontSize: 11 }} axisLine={{ stroke: GRID }} tickLine={false}
            tickFormatter={(v: number) => `${v}%`} />
          <YAxis domain={[0, 100]} tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false}
            width={40} tickFormatter={(v: number) => `${v}%`} />
          <Tooltip content={<ProbTip />} cursor={{ stroke: GRID }} />
          <ReferenceLine y={TARGET_PCT} stroke={INK3} strokeDasharray="4 4"
            label={{ value: `${TARGET_PCT}% target`, position: "insideTopLeft", fill: INK3, fontSize: 10 }} />
          {REPS.map((r) => (
            <Line key={r.key} type="monotone" dataKey={r.key} name={r.name} stroke={r.color} strokeWidth={2.5}
              dot={{ r: 3, fill: r.color }} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
      <details className="tableTwin">
        <summary>Every error level, every margin</summary>
        <div className="tableWrap">
          <table className="runsTable">
            <thead>
              <tr>
                <th>Error (sd)</th>
                {MARGINS.map((m) => <th key={m}>{m}% margin</th>)}
              </tr>
            </thead>
            <tbody>
              {R.rows.map((r) => (
                <tr key={r.error_sd_pct}>
                  <td>{r.error_sd_pct}% — {r.label}</td>
                  {MARGINS.map((m) => (
                    <td key={m}>
                      {Math.round((r.overload_prob_by_margin[m as keyof typeof r.overload_prob_by_margin] as number) * 100)}%
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <p className="calloutText">
        Even at the national demand forecaster's own accuracy — {national.error_sd_pct}% standard deviation,
        nowhere near a worst case — no margin from 0 to 30% brings the overload rate under the {TARGET_PCT}%
        target. The best is {Math.round(bestProb * 100)}%, at a {bestMargin}% margin that has already cut
        capacity to {bestCapacity} vehicles. A single feeder is far harder to forecast than the whole country, so
        the 5, 10 and 20% rows are guesses bracketing that gap, not a measurement — and they only make it worse.
        Finding 10's gain is what a scheduler earns if it knows the street's other demand exactly; this is the
        price of not knowing it, and holding back margin alone does not pay it off within the range tested.
      </p>

      <div className="chartHeader">
        <div>
          <div className="chartTitle">Re-forecasting every hour does not buy the margin back — it mostly costs more</div>
          <div className="chartMeta">
            Same unit, {M.draws} draws per cell · committing once at 18:00 against{" "}
            {natlRolling[0]?.error_sd_pct}% forecast error, the national forecaster's own accuracy
          </div>
        </div>
        <div className="legend">
          <span className="legendItem"><span className="legendSwatch" style={{ background: OK }} />Static — commit once</span>
          <span className="legendItem"><span className="legendSwatch" style={{ background: BAD }} />Rolling — re-forecast hourly</span>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={rollingRows} margin={{ top: 18, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="margin" tick={{ fill: INK3, fontSize: 11 }} axisLine={{ stroke: GRID }} tickLine={false}
            tickFormatter={(v: number) => `${v}%`} />
          <YAxis domain={[0, 100]} tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false}
            width={40} tickFormatter={(v: number) => `${v}%`} />
          <Tooltip content={<RollTip />} cursor={{ fill: "rgba(255,255,255,.03)" }} />
          <ReferenceLine y={TARGET_PCT} stroke={INK3} strokeDasharray="4 4"
            label={{ value: `${TARGET_PCT}% target`, position: "insideTopLeft", fill: INK3, fontSize: 10 }} />
          <Bar dataKey="static" name="Static" fill={OK} radius={[3, 3, 0, 0]} isAnimationActive={!reduced} />
          <Bar dataKey="rolling" name="Rolling" fill={BAD} radius={[3, 3, 0, 0]} isAnimationActive={!reduced} />
        </BarChart>
      </ResponsiveContainer>
      <details className="tableTwin">
        <summary>Every error level, static vs rolling, every margin</summary>
        <div className="tableWrap">
          <table className="runsTable">
            <thead>
              <tr><th>Error (sd)</th><th>Margin</th><th>Capacity</th><th>Static</th><th>Rolling</th></tr>
            </thead>
            <tbody>
              {M.rows.map((r) => (
                <tr key={`${r.error_sd_pct}-${r.margin_pct}`}>
                  <td>{r.error_sd_pct}%</td>
                  <td>{r.margin_pct}%</td>
                  <td>{r.capacity}</td>
                  <td>{Math.round(r.static_overload_prob * 100)}%</td>
                  <td>{Math.round(r.rolling_overload_prob * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <p className="calloutText">
        A distribution company reads its meters all night, so the obvious next question is whether correcting
        the forecast hour by hour, rather than committing once, buys back what the margin gives up. It mostly
        does not: averaged across every error level and margin tested, re-forecasting hourly overloads{" "}
        <strong>{meanDiffPp.toFixed(1)} percentage points</strong> more often than committing once, worst at{" "}
        <strong>+{((worstRow.rolling_overload_prob - worstRow.static_overload_prob) * 100).toFixed(1)}pp</strong>{" "}
        ({worstRow.error_sd_pct}% error, {worstRow.margin_pct}% margin). At zero forecast error the two agree
        exactly, which is the check that matters: fed a perfect forecast, the rolling controller must reproduce
        the static one-shot schedule, and it does. The reason it loses once the forecast is wrong is the same
        one finding 9 found for carbon — the static plan sees the whole night's (wrong) forecast at once and
        spreads its one mistake flat across every hour, while the rolling controller commits hour by hour and
        has to absorb each correction in whatever hours are still left, fewer of them as the window closes.
      </p>
    </section>
  );
}
