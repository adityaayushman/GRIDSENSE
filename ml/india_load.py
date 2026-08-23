"""Indian demand shape, taken from 46,728 measured hours instead of drawn freehand.

Source: hourly all-India and regional demand, 2019-01-01 to 2024-04-30, compiled
from Grid-India (POSOCO) daily reports and published on Kaggle as
`shubhamvashisht/hourly-load-india-electrical-load-forecasting`.

Screened before use, as every dataset in this project is:

    lag-1 +0.979   lag-24 +0.969   white-noise reference -0.007
    46,728 rows · zero nulls · zero irregular steps

Timestamps are IST. The national profile peaks at 11:00 and dips at 03:00 with a
secondary bump at 19:00 — India's characteristic twin peak, agricultural and
industrial load at midday and residential in the evening. A UTC reading would
put the peak at 16:30 local, which is not a shape any grid has.

**What this is and is not.** These are *system* demand, not the residential
share behind one distribution transformer. Using the system shape for a
residential feeder assumes the two move together, which is an approximation, and
not a conservative one: residential load is peakier than system load, because
industry runs flat around the clock. So a feeder profile shaped this way
understates the evening residential peak and therefore **overstates** the
headroom available for charging. The magnitude is separately pinned to measured
household consumption, so only the shape carries this caveat.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
CSV = HERE / "data" / "india-grid" / "india_hourly_load.csv"

REGIONS = {
    "national": "National Hourly Demand",
    "northern": "Northen Region Hourly Demand",   # spelling as published
    "western": "Western Region Hourly Demand",
    "eastern": "Eastern Region Hourly Demand",
    "southern": "Southern Region Hourly Demand",
}

#: Months grouped the way Indian grid planning treats them.
SEASONS = {
    "winter": [12, 1, 2],
    "spring": [3, 4],
    "summer": [5, 6],
    "monsoon": [7, 8, 9],
    "autumn": [10, 11],
}


def load() -> pd.DataFrame:
    if not CSV.exists():
        raise FileNotFoundError(
            f"{CSV} missing — download with:\n"
            "  kaggle datasets download -d "
            "shubhamvashisht/hourly-load-india-electrical-load-forecasting "
            "-p data/india-grid --unzip"
        )
    d = pd.read_csv(CSV, parse_dates=["datetime"])
    d["hour"] = d["datetime"].dt.hour
    d["month"] = d["datetime"].dt.month
    d["year"] = d["datetime"].dt.year
    return d


def hourly_shape(df: pd.DataFrame, region: str = "national",
                 months: list[int] | None = None) -> list[float]:
    """Mean demand by clock hour, normalised to a mean of 1.0.

    Normalising discards the level and keeps only the shape, which is the part
    this project can legitimately borrow — the level belongs to a nation, not to
    a street.
    """
    col = REGIONS[region]
    sub = df if months is None else df[df["month"].isin(months)]
    by_hour = sub.groupby("hour")[col].mean()
    mean = by_hour.mean()
    return [float(by_hour.get(h, mean) / mean) for h in range(24)]


def season_levels(df: pd.DataFrame, region: str = "national",
                  window: list[int] | None = None) -> dict[str, float]:
    """Mean overnight-window demand per season, indexed to the annual mean.

    This is the multiplier a feeder's baseline should carry from one season to
    the next: it is measured, where a flat assumption across the year is not.
    """
    col = REGIONS[region]
    sub = df if window is None else df[df["hour"].isin(window)]
    annual = sub[col].mean()
    return {
        name: round(float(sub[sub["month"].isin(months)][col].mean() / annual), 4)
        for name, months in SEASONS.items()
    }


def window_flatness(df: pd.DataFrame, region: str = "national",
                    window: list[int] | None = None) -> dict[str, float]:
    """Peak-to-valley ratio inside the charging window, per season.

    The number that decides whether coordination has anything to work with: a
    window already flat offers no valley to move load into, however constrained
    the transformer is.
    """
    col = REGIONS[region]
    sub = df if window is None else df[df["hour"].isin(window)]
    out = {}
    for name, months in SEASONS.items():
        by_hour = sub[sub["month"].isin(months)].groupby("hour")[col].mean()
        out[name] = round(float(by_hour.max() / by_hour.min()), 3)
    return out


if __name__ == "__main__":
    d = load()
    W = [h % 24 for h in range(18, 31)]
    print(f"{len(d):,} hours · {d.datetime.min().date()} -> {d.datetime.max().date()}\n")

    lv = season_levels(d, window=W)
    fl = window_flatness(d, window=W)
    print(f"{'season':<10}{'level':>8}{'peak/valley':>14}")
    for s in SEASONS:
        print(f"{s:<10}{lv[s]:>8.2f}{fl[s]:>14.2f}")

    print("\nregional summer level (overnight window, vs own annual mean):")
    for r in REGIONS:
        print(f"  {r:<10}{season_levels(d, r, W)['summer']:>7.2f}")
