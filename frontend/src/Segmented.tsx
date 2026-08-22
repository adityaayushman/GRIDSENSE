import { useEffect, useLayoutEffect, useRef, useState } from "react";

/**
 * A segmented control whose active pill slides between options.
 *
 * The pill is a pseudo-element on the container driven by two CSS variables, so
 * exactly one element moves regardless of how many options there are. Position
 * is measured from the DOM rather than assumed from an index, because the
 * options here have different label widths — an evenly-divided pill would drift
 * off the shorter ones.
 */
export default function Segmented<T extends string>({
  options, value, onChange, className = "segmented",
}: {
  options: { key: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  className?: string;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [pill, setPill] = useState({ x: 0, w: 0 });

  const measure = () => {
    const root = wrap.current;
    if (!root) return;
    const active = root.querySelector<HTMLButtonElement>("button.active");
    if (!active) return;
    // offsetLeft is relative to the positioned container, which is what the
    // pill's transform is relative to as well.
    setPill({ x: active.offsetLeft - root.clientLeft, w: active.offsetWidth });
  };

  // Before paint, so the pill never renders at 0 and then jumps.
  useLayoutEffect(measure, [value, options.length]);

  useEffect(() => {
    // Labels reflow on resize and when the webfont swaps in; both move the pill.
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    if (ro && wrap.current) ro.observe(wrap.current);
    window.addEventListener("resize", measure);
    (document as any).fonts?.ready?.then(measure).catch(() => {});
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  return (
    <div
      ref={wrap}
      className={className}
      role="tablist"
      style={{ ["--pill-x" as any]: `${pill.x}px`, ["--pill-w" as any]: `${pill.w}px` }}
    >
      {options.map((o) => (
        <button
          key={o.key}
          role="tab"
          aria-selected={value === o.key}
          className={value === o.key ? "active" : ""}
          onClick={() => onChange(o.key)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
