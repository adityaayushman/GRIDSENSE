import { useEffect, useRef } from "react";

/**
 * The opening image: a grid plane receding to a horizon, the night's carbon
 * curve hanging above it, and a vehicle drawing from it.
 *
 * Genuinely dimensional rather than a flat picture with a drop shadow — one
 * `preserve-3d` world holds six layers at different `translateZ`, so tilting it
 * moves them by different amounts and the depth is real. Still no WebGL: the
 * bundle already carries a charting library and a solver-backed API, and a
 * 3D runtime would be the largest dependency in the project for one screen.
 *
 * Pointer parallax is written to CSS custom properties on the stage rather than
 * to React state, so moving the mouse never triggers a render.
 */
export default function LandingScene({ reduced }: { reduced: boolean }) {
  const stage = useRef<HTMLDivElement>(null);
  const raf = useRef<number>();

  useEffect(() => {
    if (reduced) return;
    const el = stage.current;
    if (!el) return;

    // Listen on the whole hero, not on the stage. The copy sits above the stage
    // in the stacking order and would swallow every pointer event over the
    // middle of the screen, leaving the parallax working only at the edges.
    const host = el.closest<HTMLElement>(".ldHero") ?? el;

    const onMove = (e: PointerEvent) => {
      if (raf.current) return; // coalesce to one write per frame
      raf.current = requestAnimationFrame(() => {
        raf.current = undefined;
        const r = host.getBoundingClientRect();
        const x = (e.clientX - r.left) / r.width - 0.5;
        const y = (e.clientY - r.top) / r.height - 0.5;
        el.style.setProperty("--ry", `${x * 16}deg`);
        el.style.setProperty("--rx", `${-y * 10}deg`);
      });
    };
    const onLeave = () => {
      el.style.setProperty("--ry", "0deg");
      el.style.setProperty("--rx", "0deg");
    };

    host.addEventListener("pointermove", onMove);
    host.addEventListener("pointerleave", onLeave);
    return () => {
      host.removeEventListener("pointermove", onMove);
      host.removeEventListener("pointerleave", onLeave);
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, [reduced]);

  const anim = !reduced;

  return (
    <div className={`lsStage ${reduced ? "isStill" : ""}`} ref={stage} aria-hidden="true">
      <div className="lsWorld">
        {/* Depth 0 — the horizon the grid runs to */}
        <div className="lsLayer lsHorizon" />

        {/* Depth 1 — the transmission grid itself, laid flat and receding */}
        <div className="lsLayer lsFloor" />

        {/* Depth 2 — carbon intensity across the night, hanging over the grid */}
        <div className="lsLayer lsCurve">
          <svg viewBox="0 0 640 200" className="lsSvg">
            <defs>
              <linearGradient id="lsArc" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#d95926" stopOpacity=".9" />
                <stop offset="42%" stopColor="#8a6f7a" stopOpacity=".55" />
                <stop offset="72%" stopColor="#3987e5" stopOpacity=".95" />
                <stop offset="100%" stopColor="#3987e5" stopOpacity=".5" />
              </linearGradient>
              <linearGradient id="lsFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#3987e5" stopOpacity=".22" />
                <stop offset="100%" stopColor="#3987e5" stopOpacity="0" />
              </linearGradient>
            </defs>
            {/* The actual shape of a Spanish night: dirty at plug-in, clean after midnight */}
            <path d="M20 54 C 120 30, 210 38, 290 74 S 450 132, 540 118 S 610 92, 626 82 L626 200 L20 200 Z"
              fill="url(#lsFill)" />
            <path d="M20 54 C 120 30, 210 38, 290 74 S 450 132, 540 118 S 610 92, 626 82"
              fill="none" stroke="url(#lsArc)" strokeWidth="2.5" strokeLinecap="round" />
            {anim && (
              <circle r="4" fill="#7fb4f5">
                <animateMotion dur="9s" repeatCount="indefinite"
                  path="M20 54 C 120 30, 210 38, 290 74 S 450 132, 540 118 S 610 92, 626 82" />
                <animate attributeName="opacity" values="0;1;1;0" dur="9s" repeatCount="indefinite" />
              </circle>
            )}
            <text x="20" y="40" className="lsTick">18:00 · dirty</text>
            <text x="498" y="146" className="lsTick">03:00 · clean</text>
          </svg>
        </div>

        {/* Depth 3 — pylon, mid-ground */}
        <div className="lsLayer lsPylon">
          <svg viewBox="0 0 120 200" className="lsSvg">
            <g stroke="#4a5f7d" strokeWidth="2" fill="none" strokeLinecap="round">
              <path d="M28 196 L46 76 M92 196 L74 76" />
              <path d="M46 76 L74 76" />
              <path d="M34 156 L86 156 M38 126 L82 126" />
              <path d="M22 96 L98 96" />
              <path d="M22 96 L8 88 M98 96 L112 88" />
              <path d="M42 52 L60 38 L78 52" />
            </g>
          </svg>
        </div>

        {/* Depth 4 — the vehicle, nearest the viewer */}
        <div className="lsLayer lsCar">
          <svg viewBox="0 0 260 120" className="lsSvg">
            <defs>
              <linearGradient id="lsBody" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#2f3c50" />
                <stop offset="100%" stopColor="#151c27" />
              </linearGradient>
            </defs>
            <path d="M16 84 L26 44 C 34 24, 50 14, 74 12 L186 12
                     C 210 14, 226 24, 238 44 L248 84 Z"
              fill="url(#lsBody)" stroke="#55688a" strokeWidth="1.5" strokeLinejoin="round" />
            <path d="M44 44 C 52 28, 64 22, 80 21 L180 21
                     C 198 22, 208 30, 216 44 Z" fill="#0d141d" stroke="#44546f" />
            <rect x="16" y="76" width="232" height="13" rx="6" fill="#1b2431" stroke="#44546f" />
            <circle cx="58" cy="92" r="19" fill="#0c121a" stroke="#55688a" strokeWidth="2" />
            <circle cx="206" cy="92" r="19" fill="#0c121a" stroke="#55688a" strokeWidth="2" />
            {/* State of charge, filling */}
            <rect x="96" y="52" width="82" height="12" rx="3" fill="#0a1017" stroke="#44546f" />
            <rect x="98" y="54" width="24" height="8" rx="2" fill="#3987e5">
              {anim && <animate attributeName="width" values="8;78;8" dur="7s"
                repeatCount="indefinite" />}
            </rect>
          </svg>
        </div>

        {/* Depth 5 — energy running from grid to car, closest of all */}
        <div className="lsLayer lsFlow">
          <svg viewBox="0 0 640 120" className="lsSvg">
            <path id="lsCable" d="M120 66 C 240 104, 380 104, 520 62"
              fill="none" stroke="rgba(96,130,170,.5)" strokeWidth="2.5" strokeLinecap="round" />
            {anim && [0, 1, 2, 3].map((i) => (
              <circle key={i} r="3.5" fill="#7fb4f5">
                <animateMotion dur="2.8s" begin={`${i * 0.7}s`} repeatCount="indefinite"
                  path="M120 66 C 240 104, 380 104, 520 62" />
              </circle>
            ))}
          </svg>
        </div>
      </div>
    </div>
  );
}
