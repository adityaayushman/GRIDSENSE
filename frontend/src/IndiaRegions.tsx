import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LabelList, Cell } from "recharts";
import regions from "./data/india_regions.json";
import { usePrefersReduced, useReveal } from "./motion";

const OK = "#3987e5";
const BAD = "#d95926";
const GRID = "#2C2823";
const INK3 = "#8C8576";

const rows = regions.regions.map((r) => ({ ...r, label: r.key }));
const hh = (h: number) => `${String(Math.floor(h)).padStart(2, "0")}:${String(Math.round((h % 1) * 60)).padStart(2, "0")}`;

function Tip({ active, payload, label, unit }: any) {
  if (!active || !payload?.length) return null;
  const r = rows.find((x) => x.label === label);
  return (
    <div className="tip">
      <div className="tipHour">{r?.name ?? label}</div>
      <div className="tipRow">{payload[0].name}<b>{Number(payload[0].value).toFixed(0)}{unit}</b></div>
    </div>
  );
}

/** India is five grids, not one. Daily regional figures from the same PSP reports as the national series. */
export default function IndiaRegions() {
  const reduced = usePrefersReduced();
  const { ref, shown } = useReveal<HTMLElement>(reduced);
  const evening = rows.filter((r) => r.evening_peaking_days_pct >= 50).map((r) => r.name);
  const south = rows.find((r) => r.key === "SR")!;
  const east = rows.find((r) => r.key === "ER")!;
  return (
    <section ref={ref} className={`card reveal ${shown ? "isIn" : ""}`}>
      <div className="chartHeader">
        <div>
          <div className="chartTitle">Five grids, not one</div>
          <div className="chartMeta">
            Daily figures by region · {regions.days} Grid-India reports, {regions.span.replace("..", " to ")}
          </div>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 22 }}>
        <div>
          <div className="eyebrow" style={{ marginBottom: 6 }}>Own renewable supply, % of energy met</div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={rows} margin={{ top: 18, right: 10, left: 0, bottom: 4 }}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="label" tick={{ fill: INK3, fontSize: 11 }} axisLine={{ stroke: GRID }} tickLine={false} />
              <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} width={34} tickFormatter={(v: number) => `${v}%`} />
              <Tooltip content={<Tip unit="%" />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
              <Bar dataKey="renewable_share_pct" name="Renewable share" radius={[2, 2, 0, 0]} isAnimationActive={!reduced}>
                <LabelList dataKey="renewable_share_pct" position="top" formatter={(v: number) => `${v}%`} style={{ fill: INK3, fontSize: 11 }} />
                {rows.map((r) => <Cell key={r.key} fill={r.renewable_share_pct < 15 ? BAD : OK} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div>
          <div className="eyebrow" style={{ marginBottom: 6 }}>Days the regional peak falls 18:00–23:59, %</div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={rows} margin={{ top: 18, right: 10, left: 0, bottom: 4 }}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="label" tick={{ fill: INK3, fontSize: 11 }} axisLine={{ stroke: GRID }} tickLine={false} />
              <YAxis tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} width={34} domain={[0, 100]} tickFormatter={(v: number) => `${v}%`} />
              <Tooltip content={<Tip unit="% of days" />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
              <Bar dataKey="evening_peaking_days_pct" name="Evening-peaking" radius={[2, 2, 0, 0]} isAnimationActive={!reduced}>
                <LabelList dataKey="evening_peaking_days_pct" position="top" formatter={(v: number) => `${v}%`} style={{ fill: INK3, fontSize: 11 }} />
                {rows.map((r) => <Cell key={r.key} fill={r.evening_peaking_days_pct >= 50 ? BAD : OK} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      <details className="tableTwin">
        <summary>Table view</summary>
        <div className="tableWrap">
          <table className="runsTable">
            <thead><tr><th>Region</th><th>Renewable share</th><th>Median peak hour</th><th>Evening-peaking days</th><th>Midday-peaking days</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}><td>{r.name} ({r.key})</td><td>{r.renewable_share_pct}%</td><td>{hh(r.median_peak_hour)}</td><td>{r.evening_peaking_days_pct}%</td><td>{r.midday_peaking_days_pct}%</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <p className="calloutText">
        The {evening.join(", ")} grids peak in the <strong>evening</strong>, on more than half of days, which is when an
        EV charged on arrival adds to the peak. The {south.name} grid peaks around <strong>{hh(south.median_peak_hour)}</strong> and only{" "}
        {south.evening_peaking_days_pct}% of its days in the evening, so arriving cars land on an already-easing system. The {east.name} grid
        generates just {east.renewable_share_pct}% of what it consumes from hydro, wind and solar, the lowest of the five. These are
        daily figures and the reports carry no fuel mix per region, so this shows <em>where</em> the national numbers differ,
        not a regional carbon curve. Everything else on this page is the all-India series.
      </p>
    </section>
  );
}
