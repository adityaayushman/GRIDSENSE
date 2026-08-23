import {
  BarChart, Bar, Cell, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, LabelList, Legend, ReferenceArea, ReferenceLine,
} from "recharts";
import india from "./data/india.json";
import carbon from "./data/india_carbon.json";
import { usePrefersReduced, useReveal, useCountUp } from "./motion";

const DUMB = "#d95926";
const COORD = "#3987e5";
const GRID = "#202A36";
const INK3 = "#5F6C7B";

const H = india.headline;
const E = india.euro_comparison;
const WORST = india.seasonal_worst!;
const BEST = india.seasonal_best!;
const C = carbon;

function Panel({ children }: { children: React.ReactNode }) {
  const reduced = usePrefersReduced();
  const { ref, shown } = useReveal<HTMLElement>(reduced);
  return <section ref={ref} className={`card reveal ${shown ? "isIn" : ""}`}>{children}</section>;
}

function Gain({ v, reduced }: { v: number; reduced: boolean }) {
  const shown = useCountUp(v, reduced);
  return <>{shown.toFixed(1)}×</>;
}

function CiTip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const inWindow = label >= 18 || label < 7;
  return (
    <div className="tip">
      <div className="tipHour">{String(label).padStart(2, "0")}:00</div>
      <div className="tipRow">
        <span className="legendSwatch" style={{ background: DUMB }} />
        Carbon intensity<b>{Number(payload[0].value).toFixed(0)} g</b>
      </div>
      <div className="tipRow" style={{ color: INK3 }}>
        {inWindow ? "inside the 18-07 charging window" : "outside the window"}
      </div>
    </div>
  );
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

      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">India's clean hours are at midday, not at night</div>
            <div className="chartMeta">
              Mean carbon intensity by hour · derived from {C.days} days of Grid-India
              15-minute generation ({C.span}) with the same IPCC AR5 factors used for Spain
            </div>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={C.diurnal} margin={{ top: 8, right: 18, left: 0, bottom: 4 }}>
            <defs>
              <linearGradient id="inCi" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={DUMB} stopOpacity={0.35} />
                <stop offset="100%" stopColor={DUMB} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="hour" tick={{ fill: INK3, fontSize: 11 }} interval={1}
              axisLine={{ stroke: GRID }} tickLine={false}
              tickFormatter={(v: number) => `${String(v).padStart(2, "0")}`} />
            <YAxis domain={["dataMin - 15", "dataMax + 10"]} width={52}
              tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false}
              tickFormatter={(v: number) => `${Math.round(v)}`} />
            <Tooltip content={<CiTip />} cursor={{ stroke: GRID }} />
            {/* The window every other result in this project schedules in. */}
            <ReferenceArea x1={18} x2={23} fill="#d95926" fillOpacity={0.07} />
            <ReferenceArea x1={0} x2={7} fill="#d95926" fillOpacity={0.07} />
            <ReferenceLine y={C.mean_ci} stroke={INK3} strokeDasharray="4 4"
              label={{ value: `mean ${C.mean_ci}`, position: "insideTopRight",
                fill: INK3, fontSize: 10 }} />
            <Area type="monotone" dataKey="ci" stroke={DUMB} strokeWidth={2.5}
              fill="url(#inCi)" isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
        <p className="calloutText">
          The shaded bands are the <strong>18:00–07:00 window</strong> this project schedules in
          everywhere else. In India that is the <em>dirtiest</em> and <em>flattest</em> part of the
          day: intensity climbs steadily from {C.diurnal[18].ci} at 18:00 to a peak of{" "}
          {C.diurnal[C.dirtiest_hour].ci} at {String(C.dirtiest_hour).padStart(2, "0")}:00, while
          the real trough — {C.diurnal[C.cleanest_hour].ci} at{" "}
          {String(C.cleanest_hour).padStart(2, "0")}:00 — sits in the middle of the day, where the
          solar is. A European charging habit points Indian drivers at exactly the wrong hours.
        </p>
      </Panel>

      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">
              Twice as dirty as Spain, and worth a twentieth as much to schedule
            </div>
            <div className="chartMeta">
              100 Indian EVs · {C.days} days · median CO₂ cut against charging on arrival
            </div>
          </div>
        </div>
        <div className="matrixWrap">
          <table className="matrix">
            <thead>
              <tr>
                <th>Window</th>
                <th>Mean intensity</th>
                <th>Spread</th>
                <th>Median cut</th>
                <th>Days under 1%</th>
              </tr>
            </thead>
            <tbody>
              <tr className="matrixTotal">
                <th scope="row">Overnight 18–07 <em>(this project's default)</em></th>
                <td>{C.windows.overnight.mean_window_ci}</td>
                <td>{C.windows.overnight.window_spread_pct}%</td>
                <td className="mine">{C.windows.overnight.median_cut_pct}%</td>
                <td>{C.windows.overnight.under_1pct}%</td>
              </tr>
              <tr>
                <th scope="row">Daytime 09–17</th>
                <td>{C.windows.daytime.mean_window_ci}</td>
                <td>{C.windows.daytime.window_spread_pct}%</td>
                <td>{C.windows.daytime.median_cut_pct}%</td>
                <td>{C.windows.daytime.under_1pct}%</td>
              </tr>
              <tr>
                <th scope="row">Afternoon 12–18</th>
                <td>{C.windows.afternoon.mean_window_ci}</td>
                <td>{C.windows.afternoon.window_spread_pct}%</td>
                <td>{C.windows.afternoon.median_cut_pct}%</td>
                <td>{C.windows.afternoon.under_1pct}%</td>
              </tr>
              <tr>
                <th scope="row">Spain, overnight, for comparison</th>
                <td>{C.reference.spain_mean_ci}</td>
                <td>—</td>
                <td>{C.reference.spain_median_cut}%</td>
                <td>38.0%</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="calloutText">
          India runs at <strong>{C.mean_ci} gCO₂eq/kWh</strong> against Spain's{" "}
          {C.reference.spain_mean_ci} — twice as dirty — and overnight carbon-aware charging saves
          a median of <strong>{C.windows.overnight.median_cut_pct}%</strong>, with{" "}
          {C.windows.overnight.under_1pct}% of days offering under 1%. Spain gets{" "}
          {C.reference.spain_median_cut}%. This is finding 7 confirmed on measured Indian data:
          the value of shifting load follows a grid's <em>shape</em>, not how dirty it is.
        </p>
        <p className="calloutText">
          The afternoon row is the sharper lesson. It has the <strong>widest spread of the
          three</strong> ({C.windows.afternoon.window_spread_pct}%) and saves{" "}
          <strong>nothing at all</strong>, because six hours barely covers what a three-wheeler
          needs to charge — there is shape, but no slack to exploit it with. Shape is necessary
          and not sufficient; a scheduler also needs somewhere to move the load to.
        </p>
        <p className="calloutText">
          The policy reading is uncomfortable for this project's own premise:{" "}
          <strong>carbon-aware charging is the wrong intervention for India.</strong> Capacity
          coordination is the right one — the same fleet on the same transformer is worth{" "}
          {H.gain}× in hosting capacity, which is a real and large number, while the carbon saving
          rounds to zero.
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
