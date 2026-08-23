import { useEffect, useMemo, useRef, useState } from "react";
import { Search, CornerDownLeft } from "lucide-react";

export interface Command {
  id: string;
  label: string;
  hint?: string;
  group: string;
  keywords?: string;
  run: () => void;
}

/**
 * ⌘K / Ctrl-K command palette.
 *
 * Ranking is a subsequence match rather than a substring one, so "roco" finds
 * "Rolling control" the way a developer expects. Matches are scored on how
 * tightly the query packs into the label and whether hits land on word
 * boundaries, because a plain subsequence test alone ranks accidental
 * letter-scatter above the obvious answer.
 */
function score(query: string, text: string): number | null {
  if (!query) return 0;
  const q = query.toLowerCase();
  const t = text.toLowerCase();

  if (t.startsWith(q)) return 1000 - t.length;
  const idx = t.indexOf(q);
  if (idx >= 0) return 800 - idx * 2 - t.length * 0.1;

  // Subsequence, scored on gaps and word-boundary hits.
  let ti = 0;
  let points = 0;
  let lastHit = -1;
  for (const ch of q) {
    const found = t.indexOf(ch, ti);
    if (found === -1) return null;
    if (found === lastHit + 1) points += 6;               // consecutive
    if (found === 0 || t[found - 1] === " ") points += 10; // word start
    points -= Math.min(found - ti, 6);                     // penalise long jumps
    lastHit = found;
    ti = found + 1;
  }
  return points;
}

export default function CommandPalette({
  open, onClose, commands,
}: {
  open: boolean;
  onClose: () => void;
  commands: Command[];
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const results = useMemo(() => {
    const scored = commands
      .map((c) => ({ c, s: score(query, `${c.label} ${c.keywords ?? ""}`) }))
      .filter((r): r is { c: Command; s: number } => r.s !== null)
      .sort((a, b) => b.s - a.s);
    return scored.slice(0, 40).map((r) => r.c);
  }, [commands, query]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    // Focus after paint so the opening transition does not fight the caret.
    const t = requestAnimationFrame(() => input.current?.focus());
    return () => cancelAnimationFrame(t);
  }, [open]);

  useEffect(() => setActive(0), [query]);

  // Keep the highlighted row in view when arrowing past the fold.
  useEffect(() => {
    if (!open) return;
    listRef.current
      ?.querySelector<HTMLElement>(`[data-idx="${active}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); onClose(); }
      else if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((i) => (results.length ? (i + 1) % results.length : 0));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((i) => (results.length ? (i - 1 + results.length) % results.length : 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const cmd = results[active];
        if (cmd) { onClose(); cmd.run(); }
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, results, active, onClose]);

  if (!open) return null;

  // Group headings are emitted inline so the flat keyboard index still lines up
  // with what is on screen.
  let lastGroup = "";

  return (
    <div className="cmdScrim" onMouseDown={onClose} role="presentation">
      <div
        className="cmdPanel"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="cmdSearch">
          <Search size={16} strokeWidth={2.2} />
          <input
            ref={input}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Jump to a pane, change an objective, export the run…"
            aria-label="Search commands"
            spellCheck={false}
            autoComplete="off"
          />
          <span className="kbd">esc</span>
        </div>

        <div className="cmdList" ref={listRef} role="listbox">
          {results.length === 0 && (
            <div className="cmdEmpty">No command matches “{query}”.</div>
          )}
          {results.map((c, i) => {
            const head = c.group !== lastGroup ? ((lastGroup = c.group), c.group) : null;
            return (
              <div key={c.id}>
                {head && <div className="cmdGroup">{head}</div>}
                <button
                  data-idx={i}
                  role="option"
                  aria-selected={i === active}
                  className={`cmdItem ${i === active ? "isActive" : ""}`}
                  onMouseMove={() => setActive(i)}
                  onClick={() => { onClose(); c.run(); }}
                >
                  <span className="cmdLabel">{c.label}</span>
                  {c.hint && <span className="cmdHint">{c.hint}</span>}
                  {i === active && (
                    <CornerDownLeft className="cmdEnter" size={13} strokeWidth={2.2} />
                  )}
                </button>
              </div>
            );
          })}
        </div>

        <div className="cmdFoot">
          <span><span className="kbd">↑</span><span className="kbd">↓</span> navigate</span>
          <span><span className="kbd">↵</span> run</span>
          <span><span className="kbd">?</span> all shortcuts</span>
        </div>
      </div>
    </div>
  );
}
