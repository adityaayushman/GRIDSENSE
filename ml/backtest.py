"""Backtest the GridSense optimizer against real grid data.

The dashboard's headline number is measured against a synthetic carbon curve.
This replays the *actual* optimizer over every complete overnight window in the
ENTSO-E record and reports what the emissions saving would have been on real
data.

An 80-vehicle fleet of identical vehicles sharing one window is equivalent, for
the emissions and cost objectives, to a single aggregated vehicle with the
summed energy requirement and summed charger power — the LP has the same
feasible set in aggregate. That equivalence is asserted below, then used to keep
the 1,440-night sweep fast.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.optimizer import Vehicle, naive_schedule, optimize_schedule  # noqa: E402
from carbon import carbon_intensity  # noqa: E402

RAW = Path(__file__).parent / "data" / "raw" / "energy_dataset.csv"
ARRIVAL, DEADLINE = 18, 7
EV_COUNT, ENERGY_KWH, CHARGER_KW = 80, 9.2, 7.0


def _assert_aggregation_is_equivalent() -> None:
    """Aggregating identical vehicles must not change the emissions result."""
    rng = np.random.default_rng(0)
    carbon = list(rng.uniform(150, 400, 24))

    many = [
        Vehicle(f"v{i}", ENERGY_KWH, CHARGER_KW, ARRIVAL, DEADLINE) for i in range(EV_COUNT)
    ]
    one = [Vehicle("agg", ENERGY_KWH * EV_COUNT, CHARGER_KW * EV_COUNT, ARRIVAL, DEADLINE)]

    e_many = sum(l * c for l, c in zip(optimize_schedule(many, carbon), carbon))
    e_one = sum(l * c for l, c in zip(optimize_schedule(one, carbon), carbon))
    assert abs(e_many - e_one) < 1e-3 * max(e_many, 1.0), (e_many, e_one)
    print(f"aggregation check OK ({e_many:,.0f} vs {e_one:,.0f} gCO2)\n")


def main() -> None:
    _assert_aggregation_is_equivalent()

    df = pd.read_csv(RAW, parse_dates=["time"], index_col="time")
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("Europe/Madrid")
    ci = carbon_intensity(df).dropna()

    fleet = [Vehicle("agg", ENERGY_KWH * EV_COUNT, CHARGER_KW * EV_COUNT, ARRIVAL, DEADLINE)]
    naive = naive_schedule(fleet)

    hours = ci.index.hour
    night = ci.index.normalize() - pd.to_timedelta((hours < DEADLINE).astype(int), unit="D")
    frame = pd.DataFrame({"ci": ci.values, "night": night, "hour": hours})

    window_hours = [h % 24 for h in range(ARRIVAL, ARRIVAL + (24 - ARRIVAL + DEADLINE))]
    results = []

    for night_key, grp in frame.groupby("night"):
        # DST fall-back repeats a local hour, so collapse duplicates by mean
        # rather than indexing into a Series of two values.
        by_hour = grp.groupby("hour")["ci"].mean()
        if not set(window_hours).issubset(by_hour.index):
            continue
        # Full 24h curve; hours outside the window are unreachable anyway.
        curve = [float(by_hour.get(h, by_hour.mean())) for h in range(24)]

        opt = optimize_schedule(fleet, curve, objective="emissions")
        e_naive = sum(naive[h] * curve[h] for h in range(24)) / 1000
        e_opt = sum(opt[h] * curve[h] for h in range(24)) / 1000
        results.append((night_key, e_naive, e_opt, (1 - e_opt / e_naive) * 100))

    res = pd.DataFrame(results, columns=["night", "naive_kg", "opt_kg", "cut_pct"])
    print(f"nights backtested: {len(res):,}\n")

    print("=== emissions reduction vs naive charging, on real data (%) ===")
    print(res["cut_pct"].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9]).round(2).to_string())

    print(f"\nnights with < 1% saving : {(res['cut_pct'] < 1).sum():>5}  "
          f"({(res['cut_pct'] < 1).mean() * 100:.1f}%)")
    print(f"nights with < 5% saving : {(res['cut_pct'] < 5).sum():>5}  "
          f"({(res['cut_pct'] < 5).mean() * 100:.1f}%)")
    print(f"nights with >20% saving : {(res['cut_pct'] > 20).sum():>5}  "
          f"({(res['cut_pct'] > 20).mean() * 100:.1f}%)")

    print("\n=== fleet-wide totals across the whole record ===")
    tot_n, tot_o = res["naive_kg"].sum(), res["opt_kg"].sum()
    print(f"  naive     : {tot_n:>12,.0f} kg CO2eq")
    print(f"  optimized : {tot_o:>12,.0f} kg CO2eq")
    print(f"  reduction : {(1 - tot_o / tot_n) * 100:>12.1f} %")

    print("\n=== by season (mean % cut) ===")
    season = res["night"].dt.month % 12 // 3
    names = {0: "winter", 1: "spring", 2: "summer", 3: "autumn"}
    print(res.groupby(season.map(names))["cut_pct"].mean().round(1).to_string())

    print("\n=== what the demo currently claims on the synthetic curve ===")
    import math
    synth = [
        round(320 + 180 * math.exp(-((h - 19) ** 2) / 6) - 90 * math.exp(-((h - 13) ** 2) / 10), 1)
        for h in range(24)
    ]
    s_opt = optimize_schedule(fleet, synth, objective="emissions")
    s_naive_e = sum(naive[h] * synth[h] for h in range(24)) / 1000
    s_opt_e = sum(s_opt[h] * synth[h] for h in range(24)) / 1000
    s_cut = (1 - s_opt_e / s_naive_e) * 100
    print(f"  synthetic : {s_cut:.1f}%")
    print(f"  real median: {res['cut_pct'].median():.1f}%   real mean: {res['cut_pct'].mean():.1f}%")
    print(f"  overstatement: {s_cut / res['cut_pct'].median():.1f}x vs median")

    out = Path(__file__).parent / "data" / "backtest_nightly.csv"
    res.to_csv(out, index=False)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
