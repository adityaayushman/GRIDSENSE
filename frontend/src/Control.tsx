import {
  BarChart, Bar, Cell, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, LabelList,
} from "recharts";
import mpc from "./data/mpc.json";
import { usePrefersReduced, useReveal, useCountUp } from "./motion";

const OPT = "#3987e5";
const NEG = "#d95926";
const FLAT = "#5F6C7B";
const GRID = "#202A36";
const INK3 = "#5F6C7B";

type Strat = { mean_regret_pct: number; mean_cut_pct: number; mean_position: number | null };
const S = mpc.strategies as Record<string, Strat>;

const ARMS = [
  { key: "oneshot", name: "One-shot LP", note: "decide the night at 18:00" },
  { key: "mpc_static", name: "Rolling · same forecast", note: "re-solve hourly, learn nothing" },
  { key: "mpc", name: "Rolling · fresh forecast", note: "re-solve hourly on new data" },
  { key: "oracle", name: "Perfect foresight", note: "the floor" },
] as const;

function Panel({ children }: { children: React.ReactNode }) {
  const reduced = usePrefersReduced();
  const { ref, shown } = useReveal<HTMLElement>(reduced);
  return <section ref={ref} className={`card reveal ${shown ? "isIn" : ""}`}>{children}</section>;
}

function Pp({ value, reduced }: { value: number; reduced: boolean }) {
  const shown = useCountUp(Math.abs(value), reduced);
  return <>{value > 0 ? "+" : "−"}{shown.toFixed(3)}pp</>;
}

function MaeTip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tip">
      <div className="tipHour">{label} hour{label === 1 ? "" : "s"} ahead</div>
      <div className="tipRow">
        <span className="legendSwatch" style={{ background: OPT }} />
        Forecast error<b>{Number(payload[0].value).toFixed(2)} g</b>
      </div>
    </div>
  );
}

function RegretTip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="tip">
      <div className="tipHour">{d.name}</div>
      <div className="tipRow" style={{ color: INK3 }}>{d.note}</div>
      <div className="tipRow">
        <span className="legendSwatch" style={{ background: payload[0].fill }} />
        Regret<b>{d.regret.toFixed(3)}%</b>
      </div>
    </div>
  );
}

export default function Control() {
  const reduced = usePrefersReduced();
  const att = mpc.attribution_pp;

  const mae = Object.entries(mpc.horizon_mae).map(([h, v]) => ({
    h: Number(h), mae: v as number,
  }));

  const regret = ARMS.map((a) => ({
    name: a.name,
    note: a.note,
    regret: S[a.key].mean_regret_pct,
    position: S[a.key].mean_position,
  }));

  const worst = Math.max(...regret.map((r) => r.regret));

  return (
    <>
      <section className="hero">
        <div className="heroMain">
          <div className="eyebrow">Rolling-horizon control · {mpc.nights} held-out nights</div>
          <div className="heroValue" style={{ color: NEG }}>
            <Pp value={att.net} reduced={reduced} />
          </div>
          <div className="heroLabel">worse than deciding the whole night at 18:00</div>
          <div className="heroSub">
            Better on {mpc.mpc_better_nights} nights · identical on {mpc.mpc_tied_nights} ·
            worse on {mpc.mpc_worse_nights}
          </div>
        </div>
        <div className="heroNote">
          Grid operators re-solve as data arrives and commit only the next step, so the scheduler
          was rebuilt that way. It <strong>loses</strong>. The forecasts really do sharpen as the
          hour approaches — that part holds — but committing hour by hour costs about{" "}
          <strong>1.7×</strong> what the better information is worth.
        </div>
      </section>

      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">The premise checks out: forecasts sharpen with proximity</div>
            <div className="chartMeta">
              Mean absolute error by how far ahead the question is asked · one ridge per horizon ·
              held-out year
            </div>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={mae} margin={{ top: 8, right: 20, left: 0, bottom: 4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="h" tick={{ fill: INK3, fontSize: 11 }}
              axisLine={{ stroke: GRID }} tickLine={false}
              label={{ value: "hours ahead", position: "insideBottom", offset: -2,
                fill: INK3, fontSize: 11 }} />
            <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false}
              width={44} tickFormatter={(v: number) => `${v}g`} />
            <Tooltip content={<MaeTip />} cursor={{ stroke: GRID }} />
            <ReferenceLine y={mpc.day_ahead_mae} stroke={FLAT} strokeDasharray="4 4"
              label={{ value: `day-ahead model ${mpc.day_ahead_mae}g`, position: "insideTopLeft",
                fill: INK3, fontSize: 10 }} />
            <Line type="monotone" dataKey="mae" stroke={OPT} strokeWidth={2.5}
              dot={{ r: 2.5, fill: OPT }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
        <p className="calloutText">
          Error runs from <strong>{mpc.horizon_mae["1"]}g</strong> one hour out to{" "}
          <strong>{mpc.horizon_mae["13"]}g</strong> at thirteen — monotone throughout. Waiting
          genuinely buys information. Past <strong>h={mpc.crossover_horizon}</strong> the static
          day-ahead model is the more accurate one, so both the controller and the baseline switch
          to it there; handing the baseline the weaker forecast at long range would have
          manufactured a win out of model selection.
        </p>
      </Panel>

      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">Where the advantage goes</div>
            <div className="chartMeta">
              Mean regret against perfect foresight · each arm differs from its neighbour in
              exactly one respect
            </div>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={190}>
          <BarChart data={regret} layout="vertical"
            margin={{ top: 4, right: 64, left: 8, bottom: 4 }}>
            <CartesianGrid stroke={GRID} horizontal={false} />
            <XAxis type="number" domain={[0, worst * 1.15]} tick={{ fill: INK3, fontSize: 11 }}
              axisLine={{ stroke: GRID }} tickLine={false}
              tickFormatter={(v: number) => `${v}%`} />
            <YAxis type="category" dataKey="name" width={168}
              tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} />
            <Tooltip content={<RegretTip />} cursor={{ fill: "rgba(255,255,255,.03)" }} />
            <Bar dataKey="regret" radius={[0, 4, 4, 0]} barSize={20} isAnimationActive={false}>
              {regret.map((r) => (
                <Cell key={r.name}
                  fill={r.name.startsWith("Rolling") ? NEG : r.regret === 0 ? FLAT : OPT} />
              ))}
              <LabelList dataKey="regret" position="right"
                formatter={(v: number) => `${v.toFixed(3)}%`}
                style={{ fill: INK3, fontSize: 11 }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>

        <div className="matrixWrap">
          <table className="matrix">
            <tbody>
              <tr>
                <th scope="row">One-shot → rolling, same information</th>
                <td className="mine" style={{ color: NEG }}>+{att.rolling_commitment}pp</td>
                <td><span className="claimBad">what committing hour by hour costs</span></td>
              </tr>
              <tr>
                <th scope="row">Rolling, static → rolling, refreshed</th>
                <td className="mine" style={{ color: OPT }}>{att.fresher_forecast}pp</td>
                <td><span className="claimGood">what a sharper forecast buys</span></td>
              </tr>
              <tr className="matrixTotal">
                <th scope="row">Net</th>
                <td className="mine" style={{ color: NEG }}>+{att.net}pp</td>
                <td><span className="claimBad">the control structure costs ~1.7× what
                  the information is worth</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">Why it loses: the controller waits too long</div>
            <div className="chartMeta">
              Mean point in the window at which energy is delivered · 0 = 18:00, 12 = 06:00
            </div>
          </div>
        </div>
        <div className="matrixWrap">
          <table className="matrix">
            <thead>
              <tr><th /><th>Mean position</th><th>Mean regret</th></tr>
            </thead>
            <tbody>
              {regret.map((r) => (
                <tr key={r.name} className={r.regret === 0 ? "matrixTotal" : undefined}>
                  <th scope="row">{r.name}</th>
                  <td>{r.position === null ? "—" : r.position.toFixed(2)}</td>
                  <td>{r.regret.toFixed(3)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="calloutText">
          The rolling controller that learns nothing defers <strong>hardest of all</strong> — later
          even than perfect foresight. Each hour it weighs the hour in front of it against the{" "}
          <em>minimum</em> of a dozen noisy forecasts, and the minimum of noisy estimates is
          optimistically biased: some later hour nearly always looks cleaner than it will prove to
          be. So it waits, waits again, and ends up buying whatever the remaining hours offer. The
          one-shot LP never makes that comparison — it allocates across all thirteen hours at once,
          and its errors partly cancel.
        </p>
      </Panel>

      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">What would have made this result a lie</div>
            <div className="chartMeta">Both caught before publication; one changed the magnitude</div>
          </div>
        </div>
        <p className="calloutText">
          An early version let the one-shot baseline read the <strong>true</strong> carbon intensity
          for horizons past the crossover — handing it perfect foresight of 03:00–06:00, the
          cleanest stretch of a Spanish night. That made rolling control look <strong>238%</strong>{" "}
          worse instead of {Math.abs(mpc.mpc_closes_gap_pct)}%. The sign survived; nearly all of the
          magnitude did not.
        </p>
        <p className="calloutText">
          The machinery is checked rather than assumed: fed perfect forecasts, the rolling solver
          reproduces the one-shot optimum to <strong>0.0000%</strong> on every sampled night, and{" "}
          <code>test_optimizer_is_time_consistent</code> pins the same property in the test suite.
          The loss is a property of forecasting under commitment, not a bug.
        </p>
        <p className="calloutText">
          This is <em>certainty-equivalent</em> MPC — the standard reading of "re-solve each hour,
          execute the next step". A controller carrying a terminal cost, or one priced for the
          optionality it destroys by deferring, targets the diagnosed failure directly and was not
          tested. That remains open, and it is not evidence for the conclusion above.
        </p>
      </Panel>

      <p className="provenance">
        {mpc.nights} nights · {mpc.tested_on} · rebuilt by <code>ml/mpc.py</code> and{" "}
        <code>ml/train_horizon.py</code>
      </p>
    </>
  );
}
