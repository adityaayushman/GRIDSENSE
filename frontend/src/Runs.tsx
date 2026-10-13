import { useEffect, useState } from "react";
import { fetchRuns, RunRow } from "./api";

/**
 * Recently recorded runs, when the API has persistence switched on
 * (DATABASE_URL, see backend/app/store.py). With it off the API answers 501 and
 * this renders nothing at all, so a deployment without a database shows no
 * empty or broken panel.
 */
export default function Runs({ refreshKey }: { refreshKey: number | null | undefined }) {
  const [runs, setRuns] = useState<RunRow[] | null>(null);

  useEffect(() => {
    let live = true;
    fetchRuns(8).then((r) => { if (live) setRuns(r); });
    return () => { live = false; };
  }, [refreshKey]);

  if (!runs || runs.length === 0) return null;

  // A reduction can be negative; show that as an increase, not a bare minus sign.
  const pct = (v: number | null) => (v == null ? "—" : v >= 0 ? `${v}%` : `+${Math.abs(v)}%`);

  return (
    <section className="card">
      <div className="eyebrow">Recent runs</div>
      <div className="tableWrap">
        <table className="runsTable">
          <thead>
            <tr><th>#</th><th>Recorded</th><th>Night</th><th>Objective</th><th>Vehicles</th><th>CO₂</th><th>Cost</th><th>Peak</th></tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td>{r.id}</td>
                <td>{r.created_at.replace("T", " ").slice(0, 16)}</td>
                <td>{r.day ?? "—"}</td>
                <td>{r.objective ?? "—"}</td>
                <td>{r.ev_count ?? "—"}</td>
                <td>{pct(r.emissions_reduction_pct)}</td>
                <td>{pct(r.cost_reduction_pct)}</td>
                <td>{pct(r.peak_reduction_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
