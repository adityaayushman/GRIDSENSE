import { useEffect, useState } from "react";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import { fetchIndiaLive, IndiaLiveDay } from "./api";

const DUMB = "#d95926";
const GRID = "#202A36";
const INK3 = "#5F6C7B";

/**
 * The newest day of Indian grid carbon intensity, straight from Grid-India's daily
 * report: no key, no account. Always labelled with the day it describes and how old
 * that is, because the publisher releases yesterday's report each morning and a
 * "live" badge on day-old data would be a small lie.
 */
export default function IndiaLive() {
  const [day, setDay] = useState<IndiaLiveDay | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchIndiaLive().then((d) => live && setDay(d)).catch((e) => live && setErr(e.message));
    return () => { live = false; };
  }, []);

  if (err) {
    return (
      <section className="card">
        <div className="eyebrow">Latest Indian grid day</div>
        <p className="calloutText">Grid-India's report could not be loaded just now ({err}). The figures below are from the stored record.</p>
      </section>
    );
  }
  if (!day) {
    return <section className="card"><div className="eyebrow">Latest Indian grid day</div><p className="calloutText">Loading Grid-India's newest report…</p></section>;
  }

  const hh = (h: number) => `${String(h).padStart(2, "0")}:00`;
  return (
    <section className="card">
      <div className="chartHeader">
        <div>
          <div className="eyebrow">
            Latest Indian grid day · {day.day} · {day.age_days === 0 ? "today" : `${day.age_days} day${day.age_days === 1 ? "" : "s"} old`}
            {!day.live ? " · stored copy, live portal unreachable" : !day.fresh ? " · stale" : ""}
          </div>
          <div className="chartTitle">
            Mean {day.mean_carbon_intensity} g CO₂/kWh · cleanest at {hh(day.cleanest_hour)}, dirtiest at {hh(day.dirtiest_hour)}
          </div>
          <div className="chartMeta">
            Grid-India's Daily PSP report, 15-minute all-India generation by fuel, no key needed. It describes
            yesterday and appears the next morning, so this is the newest data the publisher offers.
          </div>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={day.hourly} margin={{ top: 8, right: 18, left: 0, bottom: 4 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="hour" tick={{ fill: INK3, fontSize: 11 }} axisLine={{ stroke: GRID }} tickLine={false}
            tickFormatter={(v: number) => String(v).padStart(2, "0")} />
          <YAxis domain={["dataMin - 15", "dataMax + 10"]} width={52} tick={{ fill: INK3, fontSize: 11 }} axisLine={false} tickLine={false} />
          <Tooltip formatter={(v: number) => [`${v} g`, "Carbon intensity"]} labelFormatter={(h: number) => hh(h)} />
          <ReferenceLine y={day.mean_carbon_intensity} stroke={INK3} strokeDasharray="4 4" />
          <Area type="monotone" dataKey="carbon_intensity" stroke={DUMB} strokeWidth={2.5} fill={DUMB} fillOpacity={0.12} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
      <p className="calloutText">
        Checked before it is shown: solar is zero at night and the fuels add up to the sheet's own total
        (median gap {day.checks.median_closure_gap_pct}%). A report that fails either is refused.
      </p>
    </section>
  );
}
