"""Data-quality pass and carbon-intensity sanity check on the ENTSO-E dataset."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / "src"))
from carbon import (  # noqa: E402
    EMISSION_FACTORS,
    carbon_intensity,
    estimate_marginal_intensity,
)

RAW = Path(__file__).parent / "data" / "raw" / "energy_dataset.csv"


def main() -> None:
    df = pd.read_csv(RAW, parse_dates=["time"], index_col="time")
    print(f"rows={len(df):,}  span={df.index.min()} -> {df.index.max()}")

    # The index is tz-aware local time (Europe/Madrid) with DST, so it is not a
    # clean hourly grid; normalise to UTC before any time-based feature work.
    df.index = pd.to_datetime(df.index, utc=True)
    expected = pd.date_range(df.index.min(), df.index.max(), freq="h", tz="UTC")
    print(f"duplicate timestamps: {df.index.duplicated().sum()}")
    print(f"missing hours vs continuous grid: {len(expected.difference(df.index))}")

    print("\n=== columns that are entirely empty or constant zero ===")
    for col in EMISSION_FACTORS:
        if col not in df.columns:
            print(f"  ABSENT  {col}")
            continue
        s = df[col]
        if s.isna().all():
            print(f"  ALL-NaN {col}")
        elif (s.fillna(0) == 0).all():
            print(f"  ALL-ZERO {col}")

    print("\n=== missingness in key columns ===")
    for col in ["total load actual", "total load forecast", "price actual",
                "forecast solar day ahead", "forecast wind onshore day ahead"]:
        print(f"  {col:38} {df[col].isna().sum():>5} NaN")

    ci = carbon_intensity(df)
    print(f"\n=== derived carbon intensity (gCO2eq/kWh) ===")
    print(f"  NaN hours : {ci.isna().sum()}")
    print(ci.describe().round(1).to_string())

    print("\n=== mean intensity by hour of day (UTC) ===")
    by_hour = ci.groupby(df.index.hour).mean().round(1)
    for h, v in by_hour.items():
        bar = "#" * int((v - by_hour.min()) / max(by_hour.max() - by_hour.min(), 1e-9) * 40)
        print(f"  {h:02d}:00  {v:6.1f}  {bar}")

    print("\n=== mean intensity by month ===")
    print(ci.groupby(df.index.month).mean().round(1).to_string())

    marginal = estimate_marginal_intensity(df)
    print(f"\n=== marginal vs average ===")
    print(f"  average intensity  : {ci.mean():.1f} gCO2eq/kWh")
    print(f"  marginal estimate  : {marginal:.1f} gCO2eq/kWh")

    # What the demo currently ships, for comparison.
    import math

    synthetic = [
        round(320 + 180 * math.exp(-((h - 19) ** 2) / 6) - 90 * math.exp(-((h - 13) ** 2) / 10), 1)
        for h in range(24)
    ]
    print(f"\n=== current synthetic curve in data_sources.py ===")
    print(f"  range {min(synthetic)} - {max(synthetic)}  (real: {by_hour.min()} - {by_hour.max()})")
    print(f"  synthetic peaks at hour {synthetic.index(max(synthetic))}, "
          f"real peaks at hour {by_hour.idxmax()}")


if __name__ == "__main__":
    main()
