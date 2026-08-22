import { useEffect, useRef, useState } from "react";

/** One source of truth for the OS motion preference, live-updated. */
export function usePrefersReduced(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" &&
      !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mq) return;
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}

/**
 * Count a number up when it changes.
 *
 * Driven by requestAnimationFrame against wall-clock time rather than a fixed
 * step per frame, so the duration holds on a 120Hz display and on a throttled
 * background tab alike. Returns the target immediately when motion is reduced,
 * and whenever the value is not finite — a NaN would otherwise animate forever.
 */
export function useCountUp(value: number, reduced: boolean, ms = 900): number {
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  const raf = useRef<number>();

  useEffect(() => {
    if (reduced || !Number.isFinite(value)) {
      setShown(value);
      from.current = value;
      return;
    }
    const start = performance.now();
    const a = from.current;
    const b = value;
    if (a === b) return;

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / ms);
      // easeOutCubic: fast arrival, gentle settle — reads as decisive.
      const e = 1 - Math.pow(1 - t, 3);
      setShown(a + (b - a) * e);
      if (t < 1) raf.current = requestAnimationFrame(tick);
      else from.current = b;
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
      from.current = value;
    };
  }, [value, reduced, ms]);

  return shown;
}

/**
 * Reveal an element once it scrolls into view.
 *
 * Unobserves after the first hit: re-animating on every scroll past is the
 * classic version of this that becomes irritating on the second pass.
 */
export function useReveal<T extends HTMLElement>(reduced: boolean) {
  const ref = useRef<T>(null);
  const [shown, setShown] = useState(reduced);

  useEffect(() => {
    if (reduced) return setShown(true);
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return setShown(true);
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true);
          io.unobserve(el);
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [reduced]);

  return { ref, shown };
}
