"""Can this project's premise be rebuilt on Indian grid data?

Short answer: not on publicly available data, and the reason is resolution
rather than availability.

India publishes a full generation mix — coal, lignite, gas, nuclear, hydro,
solar, wind — through Grid-India (formerly POSOCO) and the CEA, going back to
2013. It is **daily**. This project schedules inside an 18:00→07:00 window, so
it needs *hourly* generation mix; a daily figure is one number per day and has
no within-night shape to exploit.

What the daily data does support is a level comparison, and that turns out to
matter: India's grid is far dirtier than Spain's but far more *stable*, and
finding 7 in FINDINGS.md established that the value of carbon-aware charging
comes from a grid's shape, not from how dirty it is. So the daily data is
suggestive that India would be a poor candidate — precisely because its
emissions are steady coal rather than a varying mix. That remains a hypothesis:
confirming it needs hourly data this script does not have.

Routes to hourly Indian data, none free:
  * ElectricityMaps publishes hourly carbon intensity for Indian zones — paid.
  * RLDC "PSP" reports carry 15-minute blocks, published as PDFs; extracting a
    multi-year series means a substantial scraping and parsing job.
  * State SLDCs publish load, but load is not generation mix.

    python india_feasibility.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "src"))

POSOCO = HERE / "data" / "india-grid" / "POSOCO_data.csv"

# IPCC AR5 lifecycle factors, keyed to Grid-India's column names. Same values as
# src/carbon.py so the comparison against Spain is like-for-like.
FACTORS = {
    "India: Coal": 820.0,
    "India: Lignite": 1054.0,
    "India: Gas": 490.0,
    "India: Nuclear": 12.0,
    "India: Hydro": 24.0,
    "India: SolarGen": 45.0,
    "India: WindGen": 11.0,
}


def main() -> None:
    if not POSOCO.exists():
        print(f"missing {POSOCO}\n"
              "download: https://robbieandrew.github.io/india/data/POSOCO_data.csv")
        return

    raw = pd.read_csv(POSOCO)
    raw["date"] = pd.to_datetime(raw["yyyymmdd"], format="%Y%m%d")

    cols = [c for c in FACTORS if c in raw.columns]
    gen = raw[cols].apply(pd.to_numeric, errors="coerce")
    ok = gen.notna().all(axis=1) & (gen.sum(axis=1) > 0)
    gen, dates = gen[ok], raw.loc[ok, "date"]

    ci = sum(gen[c] * FACTORS[c] for c in cols) / gen.sum(axis=1)
    coal_share = (gen["India: Coal"] + gen.get("India: Lignite", 0)) / gen.sum(axis=1)

    print(f"Grid-India daily generation mix — {len(ci):,} days, "
          f"{dates.min().date()} to {dates.max().date()}\n")
    print(f"  carbon intensity   mean {ci.mean():>5.0f}   std {ci.std():>4.0f}   "
          f"p10 {ci.quantile(.1):>4.0f}   p90 {ci.quantile(.9):>4.0f}  gCO2eq/kWh")
    print(f"  coal + lignite     {coal_share.mean() * 100:.0f}% of generation")
    print(f"  day-to-day spread  {ci.std() / ci.mean() * 100:.1f}% of the mean\n")

    by_year = ci.groupby(dates.dt.year).mean()
    print("  annual mean:", "  ".join(f"{y}:{v:.0f}" for y, v in by_year.items()))

    print("\n  against the grids this project has hourly data for:")
    print(f"    Spain    267 gCO2eq/kWh (hourly, ENTSO-E)")
    print(f"    Germany  358 gCO2eq/kWh (hourly, ENTSO-E)")
    print(f"    India    {ci.mean():.0f} gCO2eq/kWh (DAILY — no within-night shape)")

    print("\n  The day-to-day spread above is not the number that matters. What an")
    print("  overnight charging window can exploit is variation *within* the night,")
    print("  and no public Indian source publishes generation mix at that resolution.")


if __name__ == "__main__":
    main()
