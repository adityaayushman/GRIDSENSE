"""Build the evidence bundle the dashboard's Comparison pane renders.

Everything here is *derived*, never transcribed: the forecast scores come from
artifacts/metrics.json, the savings distribution from the 1,444-night backtest,
and the LP-vs-greedy figures are recomputed on every run rather than quoted.
Re-run this after any change to the model or the optimizer and the UI follows.

    python export_evidence.py
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "src"))
sys.path.insert(0, str(HERE.parent / "backend"))

from app.optimizer import Vehicle, optimize_schedule, _available_hours  # noqa: E402

METRICS = HERE / "artifacts" / "metrics.json"
BACKTEST = HERE / "data" / "backtest_nightly.csv"
OUT = HERE.parent / "frontend" / "src" / "data" / "evidence.json"

# Bin edges chosen to make the shape of the distribution legible: the mass sits
# near zero, so the low bins are narrow and the tail is wide.
BINS = [(0, 1), (1, 5), (5, 10), (10, 20), (20, 40), (40, 101)]


def greedy(vehicles, carbon):
    """Each vehicle independently fills its own cleanest available hours."""
    load = [0.0] * 24
    for v in vehicles:
        need = v.energy_needed_kwh
        for h in sorted(_available_hours(v), key=lambda x: carbon[x]):
            if need <= 1e-9:
                break
            take = min(v.charger_kw, need)
            load[h] += take
            need -= take
    return load


def emissions(load, carbon):
    return sum(load[h] * carbon[h] for h in range(24))


def coupling_experiment() -> list[dict]:
    """Recompute the claim that the LP only beats greedy under coupling."""
    rng = random.Random(7)
    carbon = [rng.uniform(120, 400) for _ in range(24)]

    identical = [Vehicle(f"v{i}", 9.2, 7.0, 18, 7) for i in range(80)]
    mixed = [
        Vehicle(
            f"v{i}",
            rng.uniform(4, 22),
            rng.choice([3.7, 7.0, 11.0]),
            rng.choice([16, 17, 18, 19, 20, 21, 22]),
            rng.choice([5, 6, 7, 8]),
        )
        for i in range(80)
    ]
    cap = 180.0

    rows = []
    for label, fleet, feeder in (
        ("Identical vehicles", identical, None),
        ("Mixed arrivals, energy, chargers", mixed, None),
        ("Mixed + shared 180 kW feeder", mixed, cap),
    ):
        lp = optimize_schedule(fleet, carbon, feeder_capacity_kw=feeder)
        gr = greedy(fleet, carbon)
        e_lp, e_gr = emissions(lp, carbon), emissions(gr, carbon)
        rows.append(
            {
                "case": label,
                "feeder_kw": feeder,
                "lp_peak_kw": round(max(lp), 1),
                "greedy_peak_kw": round(max(gr), 1),
                "objective_gap_pct": round(abs(e_lp - e_gr) / e_lp * 100, 4),
                "greedy_violates": bool(feeder is not None and max(gr) > feeder + 1e-6),
                # Derived here rather than in the view, so the UI never has to
                # reason about the nullable feeder field.
                "greedy_over_limit_kw": (
                    round(max(max(gr) - feeder, 0.0), 1) if feeder is not None else 0.0
                ),
            }
        )
    return rows


def savings_distribution() -> dict:
    df = pd.read_csv(BACKTEST)
    cut = df["cut_pct"].clip(lower=0)
    total = len(cut)
    bins = [
        {
            "label": f"{lo}–{hi}%" if hi <= 100 else f"{lo}%+",
            "lo": lo,
            "nights": int(((cut >= lo) & (cut < hi)).sum()),
            "share_pct": round(float(((cut >= lo) & (cut < hi)).mean() * 100), 1),
        }
        for lo, hi in BINS
    ]
    return {
        "nights": total,
        "median_pct": round(float(cut.median()), 1),
        "mean_pct": round(float(cut.mean()), 1),
        "p90_pct": round(float(cut.quantile(0.9)), 1),
        "max_pct": round(float(cut.max()), 1),
        "under_1pct_share": round(float((cut < 1).mean() * 100), 1),
        "over_20pct_share": round(float((cut > 20).mean() * 100), 1),
        "fleet_total_pct": round(
            float((1 - df["opt_kg"].sum() / df["naive_kg"].sum()) * 100), 1
        ),
        "bins": bins,
    }


def git_rev() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=HERE, capture_output=True, text=True, timeout=10,
        ).stdout.strip() or None
    except Exception:
        return None


def main() -> None:
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    dist = savings_distribution()
    coupling = coupling_experiment()

    # Ordered worst-first so the chart reads as a progression.
    regret = sorted(metrics["decision_regret"], key=lambda r: r["captured_pct"])
    mae = {m["model"]: m["mae"] for m in metrics["accuracy"]}
    for r in regret:
        # metrics.json names the synthetic row differently between the two
        # tables; match on the shared prefix rather than assuming they align.
        r["mae"] = next(
            (v for k, v in mae.items() if k.startswith(r["model"][:9])), None
        )

    bundle = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_rev": git_rev(),
        "source": "ENTSO-E Spain 2015-2018 via Kaggle (CC0); IPCC AR5 emission factors",
        "note": "Generated by ml/export_evidence.py — do not edit by hand.",
        "savings": dist,
        "forecast": regret,
        "coupling": coupling,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(bundle, indent=2), encoding="utf-8")

    print(f"nights backtested   : {dist['nights']:,}")
    print(f"median / fleet total: {dist['median_pct']}% / {dist['fleet_total_pct']}%")
    print(f"under 1% / over 20% : {dist['under_1pct_share']}% / {dist['over_20pct_share']}%")
    print("coupling experiment :")
    for c in coupling:
        flag = "greedy BREACHES limit" if c["greedy_violates"] else "no coupling"
        print(f"   {c['case']:<34} gap {c['objective_gap_pct']:>7.4f}%  {flag}")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
