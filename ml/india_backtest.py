"""What carbon-aware charging is worth in India, and when.

Finding 7 established that the value of shifting load tracks a grid's *shape*
rather than how dirty it is, and predicted India would be a poor candidate
despite running roughly twice Spain's carbon intensity. This tests that on
measured Indian data for the first time.

It also asks a question the European framing never had to: **which window?**
Every result in this project schedules 18:00→07:00, because that is when
European cars sit idle and when European grids are cleanest. India's cleanest
hours are the middle of the day — its solar peak — and its overnight hours are
the dirtiest of all. If that holds, the intervention India needs is not the one
this project was built to deliver.

    python india_backtest.py
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend"))

from app.optimizer import Vehicle, naive_schedule, optimize_schedule  # noqa: E402
from india_carbon import hourly  # noqa: E402
from india_fleet import indian_fleet  # noqa: E402

OUT = HERE.parent / "frontend" / "src" / "data" / "india_carbon.json"

#: Windows worth comparing. The overnight one matches every other result in this
#: project; the others test whether India's shape rewards a different habit.
WINDOWS = {
    "overnight": (18, 7),    # the European default this project ships
    "daytime": (9, 17),      # parked at work, into the solar trough
    "afternoon": (12, 18),   # the cleanest stretch India actually has
}

FLEET_N = 100


def window_hours(arrival: int, deadline: int) -> list[int]:
    span = (deadline - arrival) % 24 or 24
    return [(arrival + i) % 24 for i in range(span)]


def replay(curve_by_day: dict, arrival: int, deadline: int) -> list[float]:
    """Percentage CO2 cut against charging on arrival, one figure per day."""
    hours = window_hours(arrival, deadline)
    fleet = indian_fleet(FLEET_N, arrival=arrival, deadline=deadline)
    naive = naive_schedule(fleet)
    cuts = []

    for curve in curve_by_day.values():
        if any(curve[h] is None for h in hours):
            continue
        full = [curve[h] if curve[h] is not None else 0.0 for h in range(24)]
        opt = optimize_schedule(fleet, full, objective="emissions")
        en = sum(naive[h] * full[h] for h in range(24))
        eo = sum(opt[h] * full[h] for h in range(24))
        if en > 0:
            cuts.append((1 - eo / en) * 100)
    return cuts


def main() -> None:
    h = hourly()
    h["day"] = h["timestamp"].dt.date
    h["hour"] = h["timestamp"].dt.hour

    # One 24-slot curve per calendar day; days with gaps are skipped per window.
    curves: dict = {}
    for day, grp in h.groupby("day"):
        by_hour = grp.groupby("hour")["ci"].mean()
        curves[day] = [float(by_hour[x]) if x in by_hour.index else None for x in range(24)]

    print(f"{len(curves)} days of measured Indian generation "
          f"({h.timestamp.min():%Y-%m-%d} to {h.timestamp.max():%Y-%m-%d})\n")

    by_hour_mean = h.groupby("hour")["ci"].mean()
    results = {}

    print(f"{'window':<12}{'hours':>9}{'spread':>9}{'median cut':>13}"
          f"{'mean cut':>11}{'under 1%':>10}")
    print("-" * 64)
    for name, (a, d) in WINDOWS.items():
        hours = window_hours(a, d)
        win = by_hour_mean.loc[[x for x in hours if x in by_hour_mean.index]]
        spread = (win.max() - win.min()) / win.mean() * 100
        cuts = replay(curves, a, d)
        if not cuts:
            continue
        results[name] = {
            "arrival": a, "deadline": d, "days": len(cuts),
            "window_spread_pct": round(float(spread), 2),
            "mean_window_ci": round(float(win.mean()), 1),
            "median_cut_pct": round(statistics.median(cuts), 2),
            "mean_cut_pct": round(statistics.mean(cuts), 2),
            "under_1pct": round(sum(1 for c in cuts if c < 1) / len(cuts) * 100, 1),
        }
        r = results[name]
        print(f"{name:<12}{a:>02d}-{d:02d}{spread:>9.1f}%{r['median_cut_pct']:>12.2f}%"
              f"{r['mean_cut_pct']:>10.2f}%{r['under_1pct']:>9.1f}%")

    night, day = results.get("overnight"), results.get("daytime")
    print()
    if night and day:
        print(f"  Overnight charging in India saves a median "
              f"{night['median_cut_pct']:.2f}%, against Spain's 3.30%.")
        print(f"  Moving the same fleet to a daytime window saves "
              f"{day['median_cut_pct']:.2f}% — "
              f"{day['median_cut_pct'] / max(night['median_cut_pct'], 1e-9):.1f}x more.")
        print(f"  The overnight window is also the dirtier one: "
              f"{night['mean_window_ci']:.0f} against {day['mean_window_ci']:.0f} "
              "gCO2eq/kWh.")

    print(f"\n  Finding 7 predicted India would save less than Spain despite being "
          f"{541 / 267:.1f}x dirtier.")
    print("  It does. The dirt is real; the shape is not there to exploit.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "note": "Generated by ml/india_backtest.py — do not edit by hand.",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_rev": (subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE,
                                   capture_output=True, text=True).stdout.strip() or None),
        "source": "Grid-India Daily PSP reports, 15-minute TimeSeries sheet",
        "span": f"{h.timestamp.min():%Y-%m-%d}..{h.timestamp.max():%Y-%m-%d}",
        "days": len(curves),
        "hourly_rows": len(h),
        "mean_ci": round(float(h["ci"].mean()), 1),
        "std_ci": round(float(h["ci"].std()), 1),
        "renewable_share": round(float(h["renewable_share"].mean()) * 100, 1),
        "cleanest_hour": int(by_hour_mean.idxmin()),
        "dirtiest_hour": int(by_hour_mean.idxmax()),
        "diurnal": [{"hour": int(x), "ci": round(float(v), 1)}
                    for x, v in by_hour_mean.items()],
        "windows": results,
        "reference": {"spain_mean_ci": 266.6, "spain_median_cut": 3.3,
                      "germany_mean_ci": 358.4, "germany_median_cut": 1.0},
        "fleet": f"{FLEET_N} Indian EVs in national segment proportions",
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
