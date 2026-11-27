import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, LabelList,
} from "recharts";
import robustness from "./data/india_robustness.json";
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
    </section>
  );
}
