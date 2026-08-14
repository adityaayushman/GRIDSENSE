"""Export real measured grid days for the API to serve.

Produces one 24-hour carbon-intensity and price curve per *charging night*.

A charging night runs 18:00 -> 07:00 and therefore spans two calendar dates, so
a single calendar day's 00-23 values would splice that evening onto the *same*
morning rather than the following one. Each exported array is stitched:

    index 18..23  ->  evening of day D
    index 00..07  ->  early morning of day D+1   (the hours actually charged)
    index 08..17  ->  midday of day D            (chart context, outside window)

This matches the construction used in backtest.py, so the figures the API
reports reproduce the backtest rather than drifting from it.

The default day is chosen as the *median* saving night, not the best one, so the
demo is representative rather than cherry-picked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.optimizer import Vehicle, naive_schedule, optimize_schedule  # noqa: E402
from carbon import carbon_intensity  # noqa: E402

RAW = Path(__file__).parent / "data" / "raw" / "energy_dataset.csv"
OUT = Path(__file__).parent.parent / "backend" / "app" / "data" / "grid_days.json"

ARRIVAL, DEADLINE = 18, 7
EV_COUNT, ENERGY_KWH, CHARGER_KW = 80, 9.2, 7.0
YEAR = 2018

# Every Nth night rather than all 361. The API bundle ships this file, and the
# full year is ~131 KB serialised, which is more payload than the demo needs —
# one night every eight days still spans every season and the full range of
# outcomes. Set STRIDE = 1 to export the complete year.
STRIDE = 8


def main() -> None:
    df = pd.read_csv(RAW, parse_dates=["time"], index_col="time")
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("Europe/Madrid")

    frame = pd.DataFrame(
        {"ci": carbon_intensity(df).values, "price": df["price actual"].values}, index=df.index
    ).dropna()
    # DST fall-back repeats a local hour; collapse before indexing by hour.
    frame = frame.groupby([frame.index.normalize(), frame.index.hour]).mean()
    frame.index.names = ["date", "hour"]

    ci_by_day = frame["ci"].unstack()
    px_by_day = frame["price"].unstack()
    complete = ci_by_day.notna().all(axis=1) & px_by_day.notna().all(axis=1)
    ci_by_day, px_by_day = ci_by_day[complete], px_by_day[complete]

    days = {}
    dates = list(ci_by_day.index)
    for i, d in enumerate(dates[:-1]):
        nxt = dates[i + 1]
        if (nxt - d).days != 1 or d.year != YEAR:
            continue  # need a genuine consecutive pair
        carbon = [
            float(ci_by_day.loc[nxt if h < DEADLINE else d, h]) for h in range(24)
        ]
        price = [
            float(px_by_day.loc[nxt if h < DEADLINE else d, h]) for h in range(24)
        ]
        days[str(d.date())] = {
            "carbon": [round(v, 1) for v in carbon],
            # EUR/MWh -> EUR/kWh, the unit the optimizer's cost objective expects.
            "price": [round(v / 1000, 5) for v in price],
        }

    # Rank nights by achievable emissions saving to pick a representative default.
    fleet = [Vehicle("agg", ENERGY_KWH * EV_COUNT, CHARGER_KW * EV_COUNT, ARRIVAL, DEADLINE)]
    naive = naive_schedule(fleet)
    cuts = {}
    for key, payload in days.items():
        c = payload["carbon"]
        opt = optimize_schedule(fleet, c, objective="emissions")
        e_n = sum(naive[h] * c[h] for h in range(24))
        e_o = sum(opt[h] * c[h] for h in range(24))
        cuts[key] = (1 - e_o / e_n) * 100 if e_n else 0.0

    # Thin *after* scoring. Taking every Nth calendar date drifts the retained
    # median well off the true one (1.0% vs 3.3% at stride 4) because saving is
    # not evenly distributed through the year. Sampling systematically along the
    # sorted saving distribution instead preserves that distribution — median
    # and both tails — by construction. This is stratification, not selection:
    # nothing is dropped for looking bad.
    full = pd.Series(cuts)
    full_median = full.median()
    kept = sorted(list(full.sort_values().index)[::STRIDE])
    days = {k: days[k] for k in kept}
    cuts = {k: cuts[k] for k in kept}

    ranked = sorted(cuts, key=lambda k: cuts[k])
    default_day = ranked[len(ranked) // 2]

    series = pd.Series(cuts)
    print(f"nights exported: {len(days)} (stride {STRIDE})")
    print(f"emissions cut across exported nights: "
          f"median {series.median():.1f}%  mean {series.mean():.1f}%")
    print(f"median across the full year, for comparison: {full_median:.1f}%")
    print(f"default day: {default_day} ({cuts[default_day]:.1f}% cut) — the median night")
    months = pd.Series([int(k[5:7]) for k in kept]).value_counts().sort_index()
    print(f"month coverage: {dict(months)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {
            "description": "Measured hourly grid carbon intensity and day-ahead price "
                           "for Spain, stitched into 18:00-07:00 charging nights. "
                           "Index 0-7 is the morning of the following day.",
            "region": "ES",
            "timezone": "Europe/Madrid",
            "units": {"carbon": "gCO2eq/kWh", "price": "EUR/kWh"},
            "source": "ENTSO-E via kaggle: "
                      "nicholasjhana/energy-consumption-generation-prices-and-weather",
            "carbon_derivation": "generation mix weighted by IPCC AR5 lifecycle "
                                 "emission factors (see ml/src/carbon.py)",
            "default_day": default_day,
            "default_day_note": "median emissions saving across all exported nights, "
                                "chosen so the demo is representative not cherry-picked",
            "days": days,
        },
        separators=(",", ":"),
    ))
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
