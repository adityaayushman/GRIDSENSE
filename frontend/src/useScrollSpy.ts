import { useEffect, useState } from "react";

/**
 * Which of the given section ids is currently the reader's section, plus how
 * far through the document they are.
 *
 * Chooses by *distance to a line a third of the way down the viewport* rather
 * than by intersection ratio. Ratio-based spies misbehave whenever sections
 * differ in height — a tall section wins on ratio while a short one the reader
 * is actually looking at loses — and this page has both.
 */
export function useScrollSpy(ids: readonly string[]) {
  const [active, setActive] = useState<string>(ids[0] ?? "");
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    let frame = 0;

    const measure = () => {
      frame = 0;
      const line = window.innerHeight * 0.34;

      let best = ids[0] ?? "";
      let bestDist = Infinity;
      for (const id of ids) {
        const el = document.getElementById(id);
        if (!el) continue;
        const { top, bottom } = el.getBoundingClientRect();
        // Straddling the line wins outright; otherwise take the nearest edge.
        const dist = top <= line && bottom >= line ? 0 : Math.min(
          Math.abs(top - line), Math.abs(bottom - line),
        );
        if (dist < bestDist) { bestDist = dist; best = id; }
      }
      setActive(best);

      const scrollable = document.documentElement.scrollHeight - window.innerHeight;
      setProgress(scrollable > 0 ? Math.min(1, window.scrollY / scrollable) : 0);
    };

    const onScroll = () => { if (!frame) frame = requestAnimationFrame(measure); };

    measure();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [ids]);

  return { active, progress };
}
