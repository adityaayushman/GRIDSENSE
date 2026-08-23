import {
  BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, LabelList, Legend,
} from "recharts";
import india from "./data/india.json";
import { usePrefersReduced, useReveal, useCountUp } from "./motion";

const DUMB = "#d95926";
const COORD = "#3987e5";
const GRID = "#202A36";
const INK3 = "#5F6C7B";

const H = india.headline;
const E = india.euro_comparison;
const WORST = india.seasonal_worst!;
const BEST = india.seasonal_best!;

function Panel({ children }: { children: React.ReactNode }) {
  const reduced = usePrefersReduced();
  const { ref, shown } = useReveal<HTMLElement>(reduced);
  return <section ref={ref} className={`card reveal ${shown ? "isIn" : ""}`}>{children}</section>;
}

function Gain({ v, reduced }: { v: number; reduced: boolean }) {
  const shown = useCountUp(v, reduced);
  return <>{shown.toFixed(1)}×</>;
}

function SeasonTip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="tip">
      <div className="tipHour" style={{ textTransform: "capitalize" }}>{label}</div>
      <div className="tipRow" style={{ color: INK3 }}>
        level {d.level.toFixed(2)}x · window peak/valley {d.peak_valley.toFixed(2)}
      </div>
      {payload.map((p: any) => (
        <div className="tipRow" key={p.dataKey}>
          <span className="legendSwatch" style={{ background: p.fill }} />
          {p.name}<b>{p.value} vehicles</b>
        </div>
      ))}
    </div>
  );
}

function CapTip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tip">
      <div className="tipHour">{label} kVA transformer</div>
      {payload.map((p: any) => (
        <div className="tipRow" key={p.dataKey}>
          <span className="legendSwatch" style={{ background: p.fill }} />
          {p.name}<b>{p.value} vehicles</b>
        </div>
      ))}
    </div>
  );
}

export default function India() {
  const reduced = usePrefersReduced();

  const caps = india.ratings
    .filter((r) => !r.overloaded)
    .map((r) => ({
      name: String(r.rating_kva),
      dumb: r.dumb,
      coordinated: r.coordinated,
      gain: r.gain,
    }));

  const seasons = india.seasonal
    .filter((s) => !s.overloaded)
    .map((s) => ({
      name: s.season.charAt(0).toUpperCase() + s.season.slice(1),
      dumb: s.dumb,
      coordinated: s.coordinated,
      level: s.level,
      peak_valley: s.peak_valley,
      worst: s.season === WORST.season,
    }));

  const segs = (["e2w", "e3w", "ecar"] as const).map((k) => {
    const s = india.fleet_per_100[k];
    return { key: k, ...s, share: s.count };
  });

  return (
    <>
      <section className="hero">
        <div className="heroMain">
          <div className="eyebrow">India · {H.rating_kva} kVA distribution transformer</div>
          <div className="heroValue" style={{ color: COORD }}>
            <Gain v={H.gain ?? 0} reduced={reduced} />
          </div>
          <div className="heroLabel">more vehicles on the same transformer</div>
          <div className="heroSub">
            {H.dumb} charging on arrival · {H.coordinated} coordinated
          </div>
        </div>
        <div className="heroNote">
          The capacity question never needed carbon data — it is load against a rating — so it is
          the part of this project that moves to India intact, and the part that matters most
          there. What changes is everything underneath it: the transformer is{" "}
          <strong>{H.rating_kva} kVA</strong>, not 1,250 kW, and the vehicles under it are
          overwhelmingly <strong>scooters and rickshaws</strong>.
        </div>
      </section>

      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">India does not drive cars</div>
            <div className="chartMeta">
              {india.fleet_mix_source} · per 100 electric vehicles sold
            </div>
          </div>
        </div>
        <div className="matrixWrap">
          <table className="matrix">
            <thead>
              <tr>
                <th />
                <th>Per 100 EVs</th>
                <th>Energy wanted</th>
                <th>Connected power</th>
                <th>Charger</th>
              </tr>
            </thead>
            <tbody>
              {segs.map((s) => (
                <tr key={s.key}>
                  <th scope="row">{s.label}</th>
                  <td>{s.count}</td>
                  <td>{s.energy_kwh} kWh</td>
                  <td>{s.connected_kw} kW</td>
                  <td>{india.segments[s.key].charger_kw} kW</td>
                </tr>
              ))}
              <tr className="matrixTotal">
                <th scope="row">All Indian EVs</th>
                <td className="mine">100</td>
                <td className="mine">{E.energy_per_100_indian_kwh} kWh</td>
                <td className="mine">{E.connected_per_100_indian_kw} kW</td>
                <td />
              </tr>
              <tr>
                <th scope="row">The same 100 as European cars</th>
                <td>100</td>
                <td>{E.energy_per_100_euro_kwh} kWh</td>
                <td>{E.connected_per_100_euro_kw} kW</td>
                <td>7 kW</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="calloutText">
          A hundred Indian EVs want{" "}
          <strong>{(E.energy_per_100_euro_kwh / E.energy_per_100_indian_kwh).toFixed(1)}× less
          energy</strong> and{" "}
          <strong>{(E.connected_per_100_euro_kw / E.connected_per_100_indian_kw).toFixed(1)}× less
          connected power</strong> than a hundred European cars. Three-wheelers are the segment
          to watch: only {india.fleet_per_100.e3w.count} vehicles of the hundred, but{" "}
          {Math.round(india.fleet_per_100.e3w.energy_kwh / E.energy_per_100_indian_kwh * 100)}% of
          the energy, because a shared rickshaw is worked all day and wants most of its pack back
          overnight.
        </p>
      </Panel>

      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">Vehicles per transformer, by rating</div>
            <div className="chartMeta">
              IS 1180 standard ratings · {india.homes} homes behind each unit ·
              apparent power converted at pf {india.power_factor}
            </div>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={caps} margin={{ top: 18, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="name" tick={{ fill: INK3, fontSize: 11 }}
              axisLine={{ stroke: GRID }} tickLine={false}
              label={{ value: "transformer rating (kVA)", position: "insideBottom",
                offset: -2, fill: INK3, fontSize: 11 }} />
            <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false}
              width={48} />
            <Tooltip content={<CapTip />} cursor={{ fill: "rgba(255,255,255,.03)" }} />
            <Legend wrapperStyle={{ fontSize: 11, color: INK3 }} />
            <Bar dataKey="dumb" name="Charging on arrival" fill={DUMB}
              radius={[4, 4, 0, 0]} isAnimationActive={false} />
            <Bar dataKey="coordinated" name="Coordinated" fill={COORD}
              radius={[4, 4, 0, 0]} isAnimationActive={false}>
              <LabelList dataKey="gain" position="top"
                formatter={(v: number) => `${v}×`}
                style={{ fill: INK3, fontSize: 11 }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <p className="calloutText">
          The coordination gain is <strong>flat across ratings</strong> — {caps[0]?.gain}× at{" "}
          {caps[0]?.name} kVA against {caps[caps.length - 1]?.gain}× at{" "}
          {caps[caps.length - 1]?.name} kVA — because both the arrival peak and the overnight
          energy scale with the transformer. What does not scale is the houses. The{" "}
          <strong>63 kVA unit is missing from this chart</strong>: {india.homes} homes draw{" "}
          {india.residential_peak_kw} kW at their own peak, which already exceeds its{" "}
          {(63 * india.power_factor).toFixed(0)} kW rating, so it hosts no vehicles at any level of
          coordination. Below a certain rating the answer is not "coordinate" but "replace the
          transformer", and scheduling cannot argue with that.
        </p>
      </Panel>

      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">The same transformer, two vehicle fleets</div>
            <div className="chartMeta">
              {H.rating_kva} kVA · charging on arrival, no coordination
            </div>
          </div>
        </div>
        <div className="matrixWrap">
          <table className="matrix">
            <tbody>
              <tr>
                <th scope="row">Indian fleet (scooters, rickshaws, some cars)</th>
                <td className="mine">{E.indian_dumb} vehicles</td>
              </tr>
              <tr>
                <th scope="row">European fleet (cars at 7 kW)</th>
                <td>{E.euro_dumb} vehicles</td>
              </tr>
              <tr className="matrixTotal">
                <th scope="row">Ratio</th>
                <td className="mine">
                  {(E.indian_dumb / Math.max(E.euro_dumb, 1)).toFixed(1)}×
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="calloutText">
          Modelling India with European vehicles would have understated what one transformer can
          carry by roughly{" "}
          <strong>{(E.indian_dumb / Math.max(E.euro_dumb, 1)).toFixed(1)}×</strong> — and pointed
          the intervention at the wrong problem. A 900 W scooter charger is not a small car
          charger; it is a different class of load, and thirteen overnight hours are enormously
          more than it needs.
        </p>
      </Panel>

      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">Capacity is not one number — it is seasonal</div>
            <div className="chartMeta">
              {H.rating_kva} kVA unit · overnight level and window shape both taken from{" "}
              {india.demand_source.rows.toLocaleString()} measured hours,{" "}
              {india.demand_source.range}
            </div>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={seasons} margin={{ top: 18, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="name" tick={{ fill: INK3, fontSize: 11 }}
              axisLine={{ stroke: GRID }} tickLine={false} />
            <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false}
              width={48} />
            <Tooltip content={<SeasonTip />} cursor={{ fill: "rgba(255,255,255,.03)" }} />
            <Legend wrapperStyle={{ fontSize: 11, color: INK3 }} />
            <Bar dataKey="dumb" name="Charging on arrival" fill={DUMB}
              radius={[4, 4, 0, 0]} isAnimationActive={false} />
            <Bar dataKey="coordinated" name="Coordinated" radius={[4, 4, 0, 0]}
              isAnimationActive={false}>
              {seasons.map((s) => (
                <Cell key={s.name} fill={s.worst ? "#d03b3b" : COORD} />
              ))}
              <LabelList dataKey="coordinated" position="top"
                style={{ fill: INK3, fontSize: 11 }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <div className="matrixWrap">
          <table className="matrix">
            <thead>
              <tr>
                <th />
                <th>Overnight level</th>
                <th>Peak / valley in window</th>
                <th>Houses alone</th>
                <th>Coordinated</th>
              </tr>
            </thead>
            <tbody>
              {india.seasonal.map((s) => (
                <tr key={s.season} className={s.season === WORST.season ? "matrixTotal" : undefined}>
                  <th scope="row" style={{ textTransform: "capitalize" }}>{s.season}</th>
                  <td>{s.level.toFixed(2)}×</td>
                  <td>{s.peak_valley.toFixed(2)}</td>
                  <td>{s.residential_peak_kw} kW</td>
                  <td className={s.season === WORST.season ? "mine" : undefined}>
                    {s.coordinated}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="calloutText">
          The same transformer hosts <strong>{BEST.coordinated}</strong> vehicles in{" "}
          {BEST.season} and <strong>{WORST.coordinated}</strong> in {WORST.season} — a{" "}
          {(BEST.coordinated / Math.max(WORST.coordinated, 1)).toFixed(2)}× spread. Two effects
          push the same way and neither cancels the other: summer overnight demand runs{" "}
          <strong>{Math.round((WORST.level / BEST.level - 1) * 100)}% higher</strong>, so there is
          less headroom, <em>and</em> the window is flatter ({WORST.peak_valley.toFixed(2)} against{" "}
          {BEST.peak_valley.toFixed(2)}) because air conditioning runs all night, so there is less
          valley to move load into. Coordination helps least exactly when the transformer is most
          stressed. Sizing on an annual average sizes for a month that never happens.
        </p>
      </Panel>

      <p className="provenance">
        {india.homes} homes · {india.daily_kwh_per_home} kWh/home/day (Delhi average) ·
        residential peak {india.residential_peak_kw} kW · window {india.window} · rebuilt by{" "}
        <code>ml/export_india_capacity.py</code>
        {india.git_rev ? ` at ${india.git_rev}` : ""}
      </p>
    </>
  );
}
