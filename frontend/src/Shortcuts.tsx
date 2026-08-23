import { X } from "lucide-react";

const GROUPS = [
  {
    name: "Navigation",
    items: [
      { keys: ["1"], what: "Simulator" },
      { keys: ["2"], what: "Existing vs GridSense" },
      { keys: ["3"], what: "Grid headroom" },
      { keys: ["4"], what: "Two grids" },
      { keys: ["5"], what: "Rolling control" },
      { keys: ["⌘", "K"], what: "Command palette" },
      { keys: ["H"], what: "Back to the overview" },
    ],
  },
  {
    name: "Simulator",
    items: [
      { keys: ["R"], what: "Re-run the current scenario" },
      { keys: ["C"], what: "Cycle objective — carbon, cost, peak" },
      { keys: ["V"], what: "Toggle vehicle-to-grid" },
      { keys: ["F"], what: "Toggle day-ahead forecast" },
      { keys: ["["], what: "Previous night" },
      { keys: ["]"], what: "Next night" },
    ],
  },
  {
    name: "Sharing",
    items: [
      { keys: ["S"], what: "Copy a link to this exact scenario" },
      { keys: ["E"], what: "Export the hourly schedule as CSV" },
      { keys: ["?"], what: "This sheet" },
    ],
  },
] as const;

export default function Shortcuts({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;
  return (
    <div className="cmdScrim" onMouseDown={onClose} role="presentation">
      <div
        className="shPanel"
        role="dialog"
        aria-modal="true"
        aria-label="Keyboard shortcuts"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="shHead">
          <h2>Keyboard shortcuts</h2>
          <button className="shClose" onClick={onClose} aria-label="Close">
            <X size={16} strokeWidth={2.2} />
          </button>
        </div>
        <div className="shGrid">
          {GROUPS.map((g) => (
            <section key={g.name}>
              <h3 className="shGroup">{g.name}</h3>
              <dl className="shList">
                {g.items.map((it) => (
                  <div className="shRow" key={it.what}>
                    <dt>{it.what}</dt>
                    <dd>{it.keys.map((k) => <span className="kbd" key={k}>{k}</span>)}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
        <p className="shFoot">
          Shortcuts are ignored while a text field has focus, so typing in the
          palette never triggers them.
        </p>
      </div>
    </div>
  );
}
