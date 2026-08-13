"""How much carbon-shifting headroom actually exists in the charging window?

GridSense's claim is that moving an EV charge inside its plug-in window cuts
emissions. The size of that prize is set by the spread of carbon intensity
*within that window on a given day* — not by the spread of long-run hourly
means, which averaging flattens.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / "src"))
from carbon import carbon_intensity  # noqa: E402

RAW = Path(__file__).parent / "data" / "raw" / "energy_dataset.csv"
ARRIVAL, DEADLINE = 18, 7  # local clock, matches the dashboard defaults


def main() -> None:
    df = pd.read_csv(RAW, parse_dates=["time"], index_col="time")
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("Europe/Madrid")
    ci = carbon_intensity(df).dropna()

    # Label each hour with the "charging night" it belongs to: hours >= 18 go
    # with that date, hours < 7 with the previous date.
    hours = ci.index.hour
    in_window = (hours >= ARRIVAL) | (hours < DEADLINE)
    night = ci.index.normalize() - pd.to_timedelta((hours < DEADLINE).astype(int), unit="D")

    win = pd.DataFrame({"ci": ci.values, "night": night, "hour": hours})[in_window]
    grp = win.groupby("night")["ci"]
    # Only keep complete 13-hour windows.
    full = grp.count() == (24 - ARRIVAL + DEADLINE)
    lo, hi, mean = grp.min()[full], grp.max()[full], grp.mean()[full]

    spread = hi - lo
    rel = spread / mean * 100
    best_cut = (mean - lo) / mean * 100

    print(f"complete overnight windows: {full.sum():,}\n")
    print("=== within-window carbon-intensity spread (max - min), gCO2eq/kWh ===")
    print(spread.describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9]).round(1).to_string())

    print("\n=== that spread as % of the window's mean ===")
    print(rel.describe(percentiles=[0.1, 0.5, 0.9]).round(1).to_string())

    print("\n=== theoretical max CO2 cut: charging entirely at the window's")
    print("=== cleanest hour vs. spreading evenly across the window (%)")
    print(best_cut.describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9]).round(1).to_string())

    print("\n=== which hour is cleanest, across all nights ===")
    cleanest = win.loc[win.groupby("night")["ci"].idxmin()]
    counts = cleanest["hour"].value_counts().sort_index()
    for h, n in counts.items():
        print(f"  {h:02d}:00  {n:5d} nights  {'#' * int(n / counts.max() * 40)}")

    # Compare against the synthetic curve the demo currently ships.
    import math

    synth = [
        320 + 180 * math.exp(-((h - 19) ** 2) / 6) - 90 * math.exp(-((h - 13) ** 2) / 10)
        for h in range(24)
    ]
    w = [h % 24 for h in range(ARRIVAL, ARRIVAL + (24 - ARRIVAL + DEADLINE))]
    s_win = [synth[h] for h in w]
    s_cut = (np.mean(s_win) - min(s_win)) / np.mean(s_win) * 100
    print("\n=== same metric on the shipped synthetic curve ===")
    print(f"  synthetic best-hour cut : {s_cut:.1f}%")
    print(f"  real median best-hour cut: {best_cut.median():.1f}%")
    print(f"  synthetic overstates the prize by {s_cut / best_cut.median():.1f}x")


if __name__ == "__main__":
    main()
