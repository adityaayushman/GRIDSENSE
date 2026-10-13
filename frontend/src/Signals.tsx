import { useMemo, useState } from "react";
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import marginal from "./data/marginal.json";
import upgrade from "./data/upgrade_inputs.json";
import Segmented from "./Segmented";
import { usePrefersReduced, useReveal } from "./motion";

const AVG = "#3987e5";
const MARG = "#d95926";
const GRID = "#2C2823";
const INK3 = "#8C8576";
const NIGHT = [18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7];
const SEASONS = ["winter", "spring", "summer", "autumn"] as const;
type Season = (typeof SEASONS)[number];

function Panel({ children }: { children: React.ReactNode }) {
  const reduced = usePrefersReduced();
  const { ref, shown } = useReveal<HTMLElement>(reduced);
  return <section ref={ref} className={`card reveal ${shown ? "isIn" : ""}`}>{children}</section>;
}

// ------------------------------------------------------------------ upgrade value
// Mirrors backend/app/upgrade_value.py from the same data file, so the sliders respond
// instantly. backend/tests/test_marginal_and_upgrade.py pins the cases both must agree on.
type Case = "low" | "base" | "high";
const CASES: Case[] = ["low", "base", "high"];
const anchors = Object.entries(upgrade.price_anchors)
  .map(([k, v]) => ({ kva: Number(k), low: v.low, high: v.high }))
  .sort((a, b) => a.kva - b.kva);

function price(kva: number, c: Case): number {
  if (c === "base") return (price(kva, "low") + price(kva, "high")) / 2;
  const [a, b] = anchors;
  const slope = (Math.log(b[c]) - Math.log(a[c])) / (Math.log(b.kva) - Math.log(a.kva));
  return Math.exp(Math.log(a[c]) + slope * (Math.log(kva) - Math.log(a.kva)));
}

const ratings = [...upgrade.ratings].sort((a, b) => a.rating_kva - b.rating_kva);
const needed = (evs: number, key: "dumb" | "coordinated") =>
  ratings.find((r) => r[key] >= evs)?.rating_kva ?? null;

function avoided(evs: number, mult: number) {
  const dumb = needed(evs, "dumb");
  const coord = needed(evs, "coordinated");
  if (coord === null) return { status: "beyond" as const, dumb, coord };
  if (dumb === null) return { status: "infeasible" as const, dumb, coord };
  const saved = Object.fromEntries(
    CASES.map((c) => [c, Math.round(price(dumb, c) * mult) - Math.round(price(coord, c) * mult)]),
  ) as Record<Case, number>;
  return { status: dumb === coord ? ("same" as const) : ("saved" as const), dumb, coord, saved };
}

const inr = (n: number) => `₹${Math.round(n).toLocaleString("en-IN")}`;

function Tip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tip">
      <div className="tipHour">{label}</div>
      {payload.map((p: any) => (
        <div className="tipRow" key={p.dataKey}>
          <span className="legendSwatch" style={{ background: p.stroke }} />
          {p.name}<b>{Math.round(p.value)} g</b>
        </div>
      ))}
    </div>
  );
}

export default function Signals() {
  const reduced = usePrefersReduced();
  const [grid, setGrid] = useState<"Spain" | "Germany" | "India">("Spain");
  const [season, setSeason] = useState<Season>("winter");
  const [evs, setEvs] = useState(100);
  const [mult, setMult] = useState(upgrade.default_install_multiplier);

  const g = marginal.grids.find((x) => x.grid === grid)!;
  const spain = marginal.grids[0];
  const series = useMemo(() => {
    const rows = (g.table as Record<string, any[]>)[season];
    return NIGHT.map((h) => ({
      hour: `${String(h).padStart(2, "0")}:00`,
      avg: rows[h].average, marg: rows[h].marginal,
    }));
  }, [g, season]);

  const r = avoided(evs, mult);
  const steps = useMemo(() => {
    // Beyond the largest on-arrival rating there is nothing to price, so stop the axis there.
    const top = Math.max(...ratings.map((x) => x.dumb));
    return Array.from({ length: Math.floor(top / 10) }, (_, i) => {
      const n = (i + 1) * 10;
      const a = avoided(n, mult);
      return { evs: n, saved: a.status === "saved" ? a.saved.base : null };
    });
  }, [mult]);

  const sv = spain.savings;
  const wideSe = Math.round(Math.max(...(spain.table as Record<string, any[]>).winter.map((x) => x.se ?? 0)));
  return (
    <>
      <section className="hero">
        <div className="heroMain">
          <div className="eyebrow">Beyond the average signal · estimated, not measured</div>
          <div className="heroValue" style={{ color: MARG }}>{spain.overnight_correlation?.toFixed(2)}</div>
          <div className="heroLabel">correlation between average and marginal carbon, Spain overnight</div>
          <div className="heroSub">Germany {marginal.grids[1].overnight_correlation} · India {marginal.grids[2].overnight_correlation}</div>
        </div>
        <div className="heroNote">
          GridSense schedules against <strong>average</strong> carbon intensity. Shifting load moves the{" "}
          <strong>marginal</strong> plant, which WattTime sells as MOER. This estimates it from public
          generation data instead. It is a <strong>proxy</strong>: it fits Spain with a median R² of{" "}
          {spain.median_r2_overnight} overnight, so read the direction, not the decimals. What it does
          show is that the two signals only loosely agree, so a schedule that looks sensible on one can look
          wrong on the other.
        </div>
      </section>

      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">Average against marginal, overnight</div>
            <div className="chartMeta">
              gCO₂eq/kWh by hour · marginal = d(dispatchable emissions) / d(residual load), 3-hour blocks
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <Segmented value={grid} onChange={setGrid}
              options={[{ key: "Spain", label: "Spain" }, { key: "Germany", label: "Germany" }, { key: "India", label: "India" }]} />
            <Segmented value={season} onChange={setSeason}
              options={SEASONS.map((s) => ({ key: s, label: s }))} />
          </div>
        </div>
        <div className="legend" style={{ marginBottom: 6 }}>
          <span className="legendItem"><span className="legendSwatch" style={{ background: AVG }} />Average</span>
          <span className="legendItem"><span className="legendSwatch" style={{ background: MARG }} />Marginal (estimated)</span>
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={series} margin={{ top: 8, right: 20, left: 0, bottom: 4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="hour" tick={{ fill: INK3, fontSize: 11 }} axisLine={{ stroke: GRID }} tickLine={false} interval={1} />
            <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} width={44}
              tickFormatter={(v: number) => `${v}`} domain={["auto", "auto"]} />
            <Tooltip content={<Tip />} cursor={{ stroke: GRID }} />
            <Line type="monotone" dataKey="avg" name="Average" stroke={AVG} strokeWidth={2.5} dot={false}
              isAnimationActive={!reduced} />
            <Line type="monotone" dataKey="marg" name="Marginal" stroke={MARG} strokeWidth={2.5} dot={false}
              strokeDasharray="5 3" isAnimationActive={!reduced} />
          </LineChart>
        </ResponsiveContainer>
        <details className="tableTwin">
          <summary>Table view</summary>
          <div className="tableWrap">
            <table className="runsTable">
              <thead><tr><th>Hour</th><th>Average</th><th>Marginal</th></tr></thead>
              <tbody>
                {series.map((s) => (
                  <tr key={s.hour}><td>{s.hour}</td><td>{Math.round(s.avg)}</td><td>{s.marg === null ? "—" : Math.round(s.marg)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </Panel>

      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">What changes when the signal changes</div>
            <div className="chartMeta">Median saving against charging on arrival, over every complete overnight window</div>
          </div>
        </div>
        <div className="matrixWrap">
          <table className="matrix">
            <thead>
              <tr><th /><th>Built on</th><th>Judged on</th><th className="mine">Median</th><th>Nights under 1%</th><th>Fit R²</th></tr>
            </thead>
            <tbody>
              {marginal.grids.flatMap((x) => [
                ["avg_on_avg", "average", "average"],
                ["avg_on_marg", "average", "marginal"],
                ["marg_on_avg", "marginal", "average"],
              ].map(([k, built, judged], i) => {
                const s = (x.savings as Record<string, any>)[k];
                return (
                  <tr key={`${x.grid}-${k}`} className={i === 0 ? "matrixTotal" : undefined}>
                    <th scope="row">{i === 0 ? x.grid : ""}</th>
                    <td>{built}</td><td>{judged}</td>
                    <td className="mine" style={{ color: s.median < 0 ? MARG : undefined }}>{s.median.toFixed(1)}%</td>
                    <td>{s.under_1pct.toFixed(0)}%</td>
                    <td>{i === 0 ? x.median_r2_overnight : ""}</td>
                  </tr>
                );
              }))}
            </tbody>
          </table>
        </div>
        <p className="calloutText">
          Read this as a stress test of the average signal, not as a better scheduler. The marginal
          figures come from a regression on public data with a modest fit in Spain and Germany
          (R² {spain.median_r2_overnight} and {marginal.grids[1].median_r2_overnight}) and a good one in India
          ({marginal.grids[2].median_r2_overnight}). Spain's {sv.avg_on_marg.median.toFixed(0)}% leans on a few evening blocks being estimated much
          cleaner than the rest of the night (winter 21:00 to 23:00 carries a standard error of about ±{wideSe} g),
          which is where charging on arrival lands. It is a flag to investigate, not a result. A true MOER series is
          the check that would settle it.
        </p>
      </Panel>

      <Panel>
        <div className="chartHeader">
          <div>
            <div className="chartTitle">What an avoided transformer upgrade is worth</div>
            <div className="chartMeta">
              Indian neighbourhood · {upgrade.homes_per_transformer} homes per transformer · a range, with its inputs showing
            </div>
          </div>
        </div>
        <div className="controls" style={{ marginBottom: 14 }}>
          <div className="field">
            <label>EVs in the neighbourhood</label>
            <input type="range" min={10} max={400} step={10} value={evs} onChange={(e) => setEvs(+e.target.value)} />
            <div className="fieldValue">{evs} vehicles</div>
          </div>
          <div className="field">
            <label>Installed cost, as a multiple of the equipment price</label>
            <input type="range" min={1} max={3} step={0.1} value={mult} onChange={(e) => setMult(+e.target.value)} />
            <div className="fieldValue">{mult.toFixed(1)}× <em>a guess</em></div>
          </div>
        </div>

        {r.status === "saved" && (
          <div className="statsGrid" style={{ marginBottom: 12 }}>
            <div className="statCard"><div className="statLabel">On arrival needs</div><div className="statValue">{r.dumb} kVA</div></div>
            <div className="statCard"><div className="statLabel">Coordinated needs</div><div className="statValue">{r.coord} kVA</div></div>
            <div className="statCard">
              <div className="statLabel">Avoided, base case</div>
              <div className="statValue">{inr(r.saved.base)}</div>
              <div className="statSub">range {inr(r.saved.low)} to {inr(r.saved.high)}</div>
            </div>
            <div className="statCard">
              <div className="statLabel">Per vehicle</div>
              <div className="statValue">{inr(r.saved.base / evs)}</div>
              <div className="statSub">{inr(r.saved.low / evs)} to {inr(r.saved.high / evs)}</div>
            </div>
          </div>
        )}
        {r.status === "same" && (
          <p className="calloutText">At {evs} vehicles both approaches fit the same {r.dumb} kVA transformer, so
            coordination avoids no upgrade here. It only saves money when it moves a neighbourhood across a rating.</p>
        )}
        {r.status === "infeasible" && (
          <p className="calloutText">Charging on arrival needs more than the largest rating modelled ({ratings[ratings.length - 1].rating_kva} kVA)
            at {evs} vehicles, while coordination fits {r.coord} kVA. The avoided cost cannot be priced from this table.</p>
        )}
        {r.status === "beyond" && <p className="calloutText">{evs} vehicles exceed every rating modelled, even coordinated.</p>}

        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={steps} margin={{ top: 8, right: 20, left: 0, bottom: 4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="evs" tick={{ fill: INK3, fontSize: 11 }} axisLine={{ stroke: GRID }} tickLine={false}
              label={{ value: "EVs", position: "insideBottom", offset: -2, fill: INK3, fontSize: 11 }} />
            <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} width={64}
              tickFormatter={(v: number) => `₹${Math.round(v / 1000)}k`} />
            <Tooltip formatter={(v: number) => inr(v)} labelFormatter={(l) => `${l} EVs`}
              contentStyle={{ background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 3 }} />
            <ReferenceLine x={evs} stroke={INK3} strokeDasharray="3 3" />
            <Area type="stepAfter" dataKey="saved" name="Avoided (base)" stroke={AVG} fill={AVG} fillOpacity={0.15}
              strokeWidth={2} isAnimationActive={!reduced} connectNulls={false} />
          </AreaChart>
        </ResponsiveContainer>
        <p className="calloutText">
          The saving arrives in steps, because transformers come in standard ratings. Prices are{" "}
          <strong>vendor asking prices for the equipment</strong>, not an official schedule of rates: no CEA or
          DISCOM source was found. Only the 100 and 200 kVA listings are real anchors; other ratings are extrapolated.
          Hosting counts come from a modelled fleet. Treat the rupees as an order of magnitude with the range showing,
          not as a measured saving.
        </p>
        <details className="tableTwin">
          <summary>Price listings used</summary>
          <div className="tableWrap">
            <table className="runsTable">
              <thead><tr><th>Rating</th><th>Vendor</th><th>Asking price</th></tr></thead>
              <tbody>
                {Object.entries(upgrade.price_anchors).flatMap(([kva, a]) =>
                  a.listings.map((l) => (
                    <tr key={`${kva}-${l.vendor}`}>
                      <td>{kva} kVA</td>
                      <td><a href={l.url} target="_blank" rel="noreferrer">{l.vendor}</a></td>
                      <td>{inr(l.inr)}</td>
                    </tr>
                  )))}
              </tbody>
            </table>
          </div>
        </details>
      </Panel>

      <p className="provenance">
        marginal proxy by <code>ml/marginal.py</code> · prices from <code>ml/export_upgrade_inputs.py</code> · API:{" "}
        <code>/api/marginal</code>, <code>/api/upgrade-value</code>
      </p>
    </>
  );
}
