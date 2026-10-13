import demo from "./data/demo_scenarios.json";

/**
 * The signature figure on the front page: one real night of the Spanish grid, drawn the way a
 * printed chart would be. Carbon intensity from 18:00 to 07:00, the hour everyone plugs in, the
 * cleanest hour of the window, and the gap between them, which is the whole opportunity.
 *
 * Read from the same demo file the offline fallback uses, so the figure on the front page is a
 * night the dashboard can open.
 */

const WINDOW = [18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7];
const W = 640, H = 330;
const M = { l: 48, r: 24, t: 44, b: 50 };

export default function NightCurve({ reduced }: { reduced: boolean }) {
  const resp = (demo as any).eras["2018"].response;
  const byHour = new Map<number, number>(resp.hourly.map((h: any) => [h.hour, h.carbon_intensity]));
  const pts = WINDOW.map((h) => ({ h, v: byHour.get(h) as number }));

  const lo = Math.floor(Math.min(...pts.map((p) => p.v)) / 20) * 20 - 20;
  const hi = Math.ceil(Math.max(...pts.map((p) => p.v)) / 20) * 20 + 20;
  const x = (i: number) => M.l + (i / (pts.length - 1)) * (W - M.l - M.r);
  const y = (v: number) => M.t + (1 - (v - lo) / (hi - lo)) * (H - M.t - M.b);

  const path = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const clean = pts.reduce((a, p, i) => (p.v < pts[a].v ? i : a), 0);
  const arrive = pts[0];
  const gap = Math.round((1 - pts[clean].v / arrive.v) * 100);
  const ticks = [lo + 20, Math.round((lo + hi) / 40) * 20, hi - 20];

  return (
    <figure className="nightFig">
      <svg viewBox={`0 0 ${W} ${H}`} role="img"
        aria-label={`Carbon intensity on the night of ${resp.day}: ${arrive.v} grams per kilowatt-hour at 18:00, ${pts[clean].v} at ${String(pts[clean].h).padStart(2, "0")}:00`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} className="nfRule" />
            <text x={M.l - 8} y={y(t) + 4} textAnchor="end" className="nfTick">{t}</text>
          </g>
        ))}
        {pts.map((p, i) => i % 2 === 0 && (
          <text key={p.h} x={x(i)} y={H - M.b + 22} textAnchor="middle" className="nfTick">
            {String(p.h).padStart(2, "0")}
          </text>
        ))}
        <text x={M.l - 8} y={M.t - 18} textAnchor="end" className="nfUnit">gCO₂/kWh</text>

        {/* the gap: what charging on arrival leaves on the table */}
        <line x1={x(clean)} x2={x(clean)} y1={y(arrive.v)} y2={y(pts[clean].v)} className="nfGap" />
        <line x1={M.l} x2={x(clean)} y1={y(arrive.v)} y2={y(arrive.v)} className="nfRef" />

        <path d={path} pathLength={1} className={`nfLine ${reduced ? "" : "nfDraw"}`} />

        <circle cx={x(0)} cy={y(arrive.v)} r={5} className="nfDotArrive" />
        <circle cx={x(clean)} cy={y(pts[clean].v)} r={5.5} className="nfDotClean" />

        <text x={x(0) + 12} y={y(arrive.v) - 34} className="nfNote">Everyone plugs in · 18:00</text>
        <text x={x(clean)} y={y(pts[clean].v) + 30} textAnchor="middle" className="nfNoteClean">
          Cleanest · {String(pts[clean].h).padStart(2, "0")}:00
        </text>
        {gap >= 6 && (
          <text x={x(clean) + 10} y={(y(arrive.v) + y(pts[clean].v)) / 2 + 4} className="nfGapLabel">
            {gap}% cleaner
          </text>
        )}
      </svg>
      <figcaption>
        One night of the Spanish grid, {resp.day}. Charging on arrival lands at the left-hand dot.
        On most nights the two dots are close together, which is why the median saving is small.
      </figcaption>
    </figure>
  );
}
