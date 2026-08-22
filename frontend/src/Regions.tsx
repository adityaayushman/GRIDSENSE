import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import regions from "./data/regions.json";
import { usePrefersReduced, useReveal } from "./motion";

const ES = "#3987e5";
const DE = "#d95926";
const GRID = "#202A36";
const INK3 = "#5F6C7B";

function Panel({ children }: { children: React.ReactNode }) {
  const reduced = usePrefersReduced();
  const { ref, shown } = useReveal<HTMLElement>(reduced);
  return <section ref={ref} className={`card reveal ${shown ? "isIn" : ""}`}>{children}</section>;
}

function ShapeTip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tip">
      <div className="tipHour">{label}</div>
      {payload.map((p: any) => (
        <div className="tipRow" key={p.dataKey}>
          <span className="legendSwatch" style={{ background: p.stroke }} />
          {p.name}
          <b>{p.value > 0 ? "+" : ""}{Number(p.value).toFixed(1)}%</b>
        </div>
      ))}
    </div>
  );
}

export default function Regions() {
  const [es, de] = regions.regions;

  // Both shapes are indexed by position in the 18:00→07:00 window, so two grids
  // in different time zones line up hour-for-hour.
  const shape = es.shape.map((p: any, i: number) => ({
    hour: p.hour,
    es: p.rel,
    de: de.shape[i]?.rel ?? null,
  }));

  return (
    <>
      <section className="hero">
        <div className="heroMain">
          <div className="eyebrow">Two grids · same optimizer</div>
          <div className="heroValue" style={{ color: ES }}>3.3<span style={{ fontSize: 30 }}>%</span></div>
          <div className="heroLabel">median night saving in Spain</div>
          <div className="heroSub">Germany, on the same model: {de.median_saving.toFixed(1)}%</div>
        </div>
        <div className="heroNote">
          Germany's grid is <strong>dirtier</strong> ({de.mean} vs {es.mean} gCO₂eq/kWh) and{" "}
          <strong>swings harder</strong> (σ {de.std} vs {es.std}), which ought to make it the better
          place to shift load. It is worse — <strong>{de.under_1pct}%</strong> of its nights offer
          under 1%, against {es.under_1pct}% in Spain. The reason is not in these numbers.
        </div>
      </section>

      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">The average shape of a charging night</div>
            <div className="chartMeta">
              % above or below each grid's own night-mean intensity · aligned by position in the
              18:00→07:00 window, so two time zones compare directly
            </div>
          </div>
          <div className="legend">
            <span className="legendItem"><span className="legendSwatch" style={{ background: ES }} />Spain</span>
            <span className="legendItem"><span className="legendSwatch" style={{ background: DE }} />Germany</span>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={shape} margin={{ top: 8, right: 18, left: 0, bottom: 4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="hour" interval={1} tick={{ fill: INK3, fontSize: 11 }}
              axisLine={{ stroke: GRID }} tickLine={false} />
            <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false}
              width={48} tickFormatter={(v: number) => `${v > 0 ? "+" : ""}${v}%`} />
            <Tooltip content={<ShapeTip />} cursor={{ stroke: GRID }} />
            <ReferenceLine y={0} stroke="#4A5563" strokeWidth={1} />
            <Line type="linear" dataKey="es" name="Spain" stroke={ES} strokeWidth={2}
              dot={false} isAnimationActive={false} />
            <Line type="linear" dataKey="de" name="Germany" stroke={DE} strokeWidth={2}
              dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
        <p className="calloutText">
          Both curves start <strong>below zero</strong>. On average, 18:00 — the hour everyone
          plugs in — is already the cleanest hour of the window, and Germany's advantage there is
          larger ({de.shape[0].rel}% against Spain's {es.shape[0].rel}%). Charging on arrival is
          landing on the best hour by accident, which leaves the optimizer less to win back. That,
          not flatness, is why the dirtier grid saves less.
        </p>
      </Panel>

      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">Why the obvious statistics mislead</div>
            <div className="chartMeta">
              Every measure of how dirty or how variable a grid is points the wrong way here
            </div>
          </div>
        </div>
        <div className="matrixWrap">
          <table className="matrix">
            <thead>
              <tr>
                <th />
                <th>Spain</th>
                <th>Germany</th>
                <th>Predicts the saving?</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Mean carbon intensity</th>
                <td>{es.mean}</td><td>{de.mean}</td>
                <td><span className="claimBad">No — dirtier, saves less</span></td>
              </tr>
              <tr>
                <th scope="row">Standard deviation</th>
                <td>{es.std}</td><td>{de.std}</td>
                <td><span className="claimBad">No — swings more, saves less</span></td>
              </tr>
              <tr>
                <th scope="row">Spread within the window</th>
                <td>{es.median_window_spread_pct}%</td><td>{de.median_window_spread_pct}%</td>
                <td><span className="claimBad">No — wider spread, saves less</span></td>
              </tr>
              <tr>
                <th scope="row">Arrival hour vs night mean</th>
                <td>{es.shape[0].rel}%</td><td>{de.shape[0].rel}%</td>
                <td><span className="claimGood">Yes — the better arrival is, the
                  less there is to gain</span></td>
              </tr>
              <tr className="matrixTotal">
                <th scope="row">Median night saving</th>
                <td className="mine">{es.median_saving}%</td>
                <td>{de.median_saving.toFixed(1)}%</td>
                <td><span className="claimNote">{es.nights} / {de.nights} nights</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="calloutText">
          The intuition that a dirty, volatile grid is the profitable place to shift load is
          wrong, and three separate statistics endorse it. What matters is how good the default
          behaviour already is: if people happen to plug in during a clean hour, a scheduler has
          little left to recover no matter how much carbon the grid burns overall.
        </p>
      </Panel>

      <p className="provenance">
        {es.source} · {de.source} · rebuilt by <code>ml/export_regions.py</code>
        {regions.git_rev ? ` at ${regions.git_rev}` : ""}
      </p>
    </>
  );
}
