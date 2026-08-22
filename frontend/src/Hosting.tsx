import { useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, ReferenceDot,
} from "recharts";
import hosting from "./data/hosting.json";

// Validated dark-band trio, all-pairs clean on this surface.
const DUMB = "#d95926";
const UNCO = "#199e70";
const COORD = "#3987e5";
const LIMIT = "#d03b3b";
const GRID = "#202A36";
const INK3 = "#5F6C7B";

const SERIES = [
  { key: "dumb_kw", name: "Charging on arrival", colour: DUMB, cap: "dumb" },
  { key: "uncoordinated_kw", name: "Uncoordinated carbon-aware", colour: UNCO, cap: "uncoordinated" },
  { key: "coordinated_kw", name: "Coordinated (this project)", colour: COORD, cap: "coordinated" },
] as const;

function Tip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tip">
      <div className="tipHour">{label} EVs on the street</div>
      {payload.map((p: any) => (
        <div className="tipRow" key={p.dataKey}>
          <span className="legendSwatch" style={{ background: p.stroke }} />
          {p.name}
          <b>{Math.round(p.value)} kW</b>
        </div>
      ))}
    </div>
  );
}

export default function Hosting() {
  const [rating, setRating] = useState<number>(hosting.headline_rating_kw);
  // Headline figures come from the REALISTIC fleet. The identical-fleet numbers
  // are kept only as contrast: making every car arrive at the same instant
  // maximally penalises charge-on-arrival and roughly doubles the apparent gain.
  const caps: any = (hosting as any).realistic.find((c: any) => c.rating_kw === rating);
  const identical: any = hosting.capacities.find((c: any) => c.rating_kw === rating);

  // The stored curve carries one coordinated column per rating; project the
  // selected one onto a stable key so the chart does not re-map series.
  const data = hosting.curve.map((r: any) => ({
    evs: r.evs,
    dumb_kw: r.dumb_kw,
    uncoordinated_kw: r.uncoordinated_kw,
    coordinated_kw: r[`coordinated_${rating}_kw`],
  }));

  /** Where a strategy's curve crosses the transformer rating. */
  const crossing = (key: string) => {
    const hit = data.find((r: any) => r[key] != null && r[key] > rating);
    return hit ? hit.evs : null;
  };

  const ratio = caps.gain != null ? caps.gain.toFixed(1) : "—";

  return (
    <>
      <section className="hero">
        <div className="heroMain">
          <div className="eyebrow">Hosting capacity · {rating} kW transformer</div>
          <div className="heroValue" style={{ color: COORD }}>{ratio}×</div>
          <div className="heroLabel">more EVs on the same transformer</div>
          <div className="heroSub">
            {caps.coordinated} coordinated vs {caps.dumb} charging on arrival ·
            median of {caps.nights_sampled} nights
          </div>
        </div>
        <div className="heroNote">
          A distribution planner's actual question is not how much CO₂ a schedule saves — it is
          how much EV adoption a feeder can absorb before it has to be dug up and replaced.
          Charging on arrival uses one or two hours of a thirteen-hour window, so it hits the
          rating on <strong>instantaneous power</strong> while most of the night sits empty.
          Coordinating the street spreads the same energy across the window, and the binding
          constraint becomes <strong>energy</strong> instead. That is where the multiple comes
          from — and it is a deferred capital upgrade, not a rounding error.
        </div>
      </section>

      <section className="card">
        <div className="chartHeader">
          <div>
            <div className="chartTitle">Peak load as EV adoption grows</div>
            <div className="chartMeta">
              kW · {hosting.homes} existing homes ({hosting.residential_peak_kw} kW residential
              peak) · median across {hosting.nights} nights · simplified fleet, all arriving
              18:00 — the headline above uses staggered arrivals
            </div>
          </div>
          <div className="legend">
            {SERIES.map((s) => (
              <span className="legendItem" key={s.key}>
                <span className="legendSwatch" style={{ background: s.colour }} />
                {s.name}
              </span>
            ))}
          </div>
        </div>

        <div className="ratingPicker">
          <span className="ratingLabel">Transformer rating</span>
          {hosting.ratings.map((r: number) => (
            <button key={r} onClick={() => setRating(r)}
              className={`ratingBtn ${r === rating ? "active" : ""}`}>{r} kW</button>
          ))}
        </div>

        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="evs" tick={{ fill: INK3, fontSize: 11 }} axisLine={{ stroke: GRID }}
              tickLine={false} label={{ value: "EVs on the street", position: "insideBottom",
                offset: -2, fill: INK3, fontSize: 11 }} height={44} />
            <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} width={56} />
            <Tooltip content={<Tip />} cursor={{ stroke: GRID }} />
            <ReferenceLine y={rating} stroke={LIMIT} strokeWidth={1.5} strokeDasharray="5 4"
              label={{ value: `${rating} kW transformer rating`, position: "insideTopRight",
                fill: LIMIT, fontSize: 10.5 }} />
            {SERIES.map((s) => (
              <Line key={s.key} type="linear" dataKey={s.key} name={s.name} stroke={s.colour}
                strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
            ))}
            {SERIES.map((s) => {
              const x = crossing(s.key);
              return x == null ? null : (
                <ReferenceDot key={`x-${s.key}`} x={x} y={rating} r={4.5} fill={s.colour}
                  stroke="#131922" strokeWidth={2} isFront />
              );
            })}
          </LineChart>
        </ResponsiveContainer>

        <p className="calloutText">
          Both uncoordinated strategies climb in a straight line with adoption, so every
          transformer rating is only a matter of time. Coordination flattens the curve against
          the limit instead — the schedule absorbs the growth rather than the copper. Being
          carbon-aware but uncoordinated helps a little, buying{" "}
          <strong>{identical.uncoordinated - identical.dumb} extra EVs</strong> in this
          simplified fleet; coordinating the street buys{" "}
          <strong>{caps.coordinated - caps.dumb}</strong> once arrivals stagger realistically.
        </p>
      </section>

      <section className="card">
        <div className="chartHeader">
          <div>
            <div className="chartTitle">Hosting capacity by transformer rating</div>
            <div className="chartMeta">
              EVs supported before the median night exceeds the rating · realistic fleet:
              staggered arrivals, mixed energy needs, 3.7/7/11 kW charger mix
            </div>
          </div>
        </div>
        <div className="matrixWrap">
          <table className="matrix">
            <thead>
              <tr>
                <th>Transformer</th>
                <th>Charging on arrival</th>
                <th className="mine">Coordinated</th>
                <th>Gain</th>
                <th>Same, identical fleet</th>
              </tr>
            </thead>
            <tbody>
              {(hosting as any).realistic.map((c: any) => {
                const id = hosting.capacities.find((k: any) => k.rating_kw === c.rating_kw)!;
                return (
                  <tr key={c.rating_kw}>
                    <th scope="row">{c.rating_kw} kW</th>
                    <td>{c.dumb} EVs</td>
                    <td className="mine">
                      {c.coordinated} EVs
                      <span className="claimNote">solver-bisected</span>
                    </td>
                    <td><strong>{c.gain.toFixed(1)}×</strong></td>
                    <td>
                      {(id.coordinated / id.dumb).toFixed(1)}×
                      <span className="claimNote">all arriving 18:00</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="calloutText">
          The coordinated ceiling is where the night physically runs out of headroom, not where
          the sweep stopped — found by bisecting the solver itself, bounded by an energy
          argument so the search can never report its own limit as a result. The last column is
          what the same calculation claims when every car arrives at 18:00: roughly double,
          because a synchronised arrival maximally penalises the baseline it is measured
          against. That assumption was inflating this figure, which is why the realistic fleet
          is the one quoted.
        </p>
      </section>

      <p className="provenance">
        Rebuilt by <code>ml/export_hosting_capacity.py</code>
        {hosting.git_rev ? ` at ${hosting.git_rev}` : ""} ·{" "}
        {new Date(hosting.generated_at).toISOString().slice(0, 10)}
      </p>
    </>
  );
}
