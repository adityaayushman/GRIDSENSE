"""Compare two grids, and export what the dashboard needs to show why they differ.

The Spanish result — a 3.3% median night saving — is one grid's number. Germany
is dirtier and swings harder, which ought to make it a better place to shift
load. It is worse. The reason is not visible in summary statistics, so this
exports the thing that does explain it: the average shape of a charging night in
each grid.

Spain dips after midnight as solar leaves the mix and demand falls. Germany sits
flat on lignite overnight. A scheduler can only exploit shape, and Germany's
variance is between days rather than within nights.

    python export_regions.py
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "src"))
sys.path.insert(0, str(HERE.parent / "backend"))

from app.optimizer import Vehicle, naive_schedule, optimize_schedule  # noqa: E402
from carbon import EMISSION_FACTORS  # noqa: E402

OUT = HERE.parent / "frontend" / "src" / "data" / "regions.json"
ARRIVAL, DEADLINE = 18, 7
WINDOW = [h % 24 for h in range(ARRIVAL, ARRIVAL + (24 - ARRIVAL + DEADLINE))]

# The German export names its columns differently; same IPCC AR5 factors.
DE_FACTORS = {
    "biomass": 230.0, "fossil_brown_coal_lignite": 1054.0,
    "fossil_coal_derived_gas": 820.0, "fossil_gas": 490.0,
    "fossil_hard_coal": 820.0, "fossil_oil": 650.0, "geothermal": 38.0,
    "hydro_run_of_river": 24.0, "hydro_water_reservoir": 24.0,
    "hydro_pumped_storage": 24.0, "nuclear": 12.0, "others": 700.0,
    "waste": 700.0, "wind_offshore_mw": 11.0, "wind_onshore_mw": 11.0,
    "solar_mw": 45.0,
}


def spain() -> pd.Series:
    e = pd.read_csv(HERE / "data/raw/energy_dataset.csv", parse_dates=["time"], index_col="time")
    e.index = pd.to_datetime(e.index, utc=True)
    e = e[~e.index.duplicated()].sort_index()
    cols = [c for c in EMISSION_FACTORS if c in e.columns]
    g = e[cols].fillna(0.0)
    return (sum(g[c] * EMISSION_FACTORS[c] for c in cols)
            / g.sum(axis=1).replace(0, np.nan)).dropna()


def germany() -> pd.Series:
    d = pd.read_csv(HERE / "data/de/de_lu_hourly.csv", parse_dates=["ts_utc"])
    d = d.set_index("ts_utc").sort_index()
    g = d[list(DE_FACTORS)].fillna(0.0)
    return (sum(g[c] * DE_FACTORS[c] for c in DE_FACTORS)
            / g.sum(axis=1).replace(0, np.nan)).dropna()


def profile(ci: pd.Series, tz: str) -> dict:
    """Summary stats, the average night's shape, and the achievable saving."""
    loc = ci.index.tz_convert(tz)
    hours = loc.hour
    night = loc.normalize() - pd.to_timedelta((hours < DEADLINE).astype(int), unit="D")
    f = pd.DataFrame({"ci": ci.values, "h": hours, "n": night})

    fleet = [Vehicle("agg", 9.2 * 80, 7.0 * 80, ARRIVAL, DEADLINE)]
    naive = naive_schedule(fleet)

    cuts, spreads = [], []
    for _, grp in f.groupby("n"):
        by = grp.groupby("h")["ci"].mean()
        if not set(WINDOW).issubset(by.index):
            continue
        curve = [float(by.get(h, by.mean())) for h in range(24)]
        opt = optimize_schedule(fleet, curve, objective="emissions")
        en = sum(naive[h] * curve[h] for h in range(24))
        eo = sum(opt[h] * curve[h] for h in range(24))
        if en > 0:
            cuts.append((1 - eo / en) * 100)
        win = [curve[h] for h in WINDOW]
        spreads.append((max(win) - min(win)) / (sum(win) / len(win)) * 100)

    # Mean shape of a night, indexed by position in the window rather than by
    # clock hour, so the two grids line up despite different time zones.
    shape = [float(f[f.h == h]["ci"].mean()) for h in WINDOW]
    mean_shape = sum(shape) / len(shape)

    return {
        "mean": round(float(ci.mean()), 1),
        "std": round(float(ci.std()), 1),
        "p10": round(float(ci.quantile(0.1)), 1),
        "p90": round(float(ci.quantile(0.9)), 1),
        "nights": len(cuts),
        "median_saving": round(statistics.median(cuts), 1),
        "mean_saving": round(statistics.mean(cuts), 1),
        "under_1pct": round(sum(1 for c in cuts if c < 1) / len(cuts) * 100, 1),
        "over_20pct": round(sum(1 for c in cuts if c > 20) / len(cuts) * 100, 1),
        # The number that actually predicts the saving.
        "median_window_spread_pct": round(statistics.median(spreads), 1),
        "shape": [
            {"pos": i, "hour": f"{h:02d}:00", "ci": round(v, 1),
             "rel": round((v / mean_shape - 1) * 100, 1)}
            for i, (h, v) in enumerate(zip(WINDOW, shape))
        ],
    }


def main() -> None:
    regions = [
        {"code": "ES", "name": "Spain", "tz": "Europe/Madrid",
         "source": "ENTSO-E 2015-2018", **profile(spain(), "Europe/Madrid")},
        {"code": "DE", "name": "Germany", "tz": "Europe/Berlin",
         "source": "ENTSO-E DE-LU 2023-2026", **profile(germany(), "Europe/Berlin")},
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_rev": (subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE,
                                   capture_output=True, text=True).stdout.strip() or None),
        "note": "Generated by ml/export_regions.py — do not edit by hand.",
        "window": f"{ARRIVAL:02d}:00-{DEADLINE:02d}:00",
        "regions": regions,
    }, indent=1), encoding="utf-8")

    print(f"{'':<9} {'mean':>7} {'std':>7} {'median cut':>11} {'under 1%':>9} {'win spread':>11}")
    for r in regions:
        print(f"{r['name']:<9} {r['mean']:>7} {r['std']:>7} {r['median_saving']:>10}% "
              f"{r['under_1pct']:>8}% {r['median_window_spread_pct']:>10}%")
    print(f"\nwrote {OUT} ({OUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
