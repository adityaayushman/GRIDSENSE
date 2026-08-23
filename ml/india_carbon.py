"""Hourly Indian carbon intensity, derived the same way the Spanish series is.

Input is `fetch_india_psp.py`'s output: 15-minute all-India generation by fuel,
straight from Grid-India's Daily PSP reports. Output is an hourly gCO2eq/kWh
series built by weighting each fuel's generation by its IPCC AR5 lifecycle
emission factor — identical methodology to `src/carbon.py`, which is what makes
India and Spain comparable at all. Nothing is taken from a third party's
pre-computed carbon number.

Two modelling choices worth stating plainly:

**Thermal is treated as coal.** The sheet reports one THERMAL column and India's
thermal fleet is overwhelmingly coal, but it does include lignite, which is
dirtier (1054 against 820). Using the coal factor therefore *understates* Indian
carbon intensity slightly. The alternative — splitting the column by the annual
coal/lignite ratio — would invent structure the source does not report.

**Storage is excluded from the mix.** A discharging battery emits nothing itself;
its emissions belong to whatever charged it. Counting it as zero-carbon
generation would dilute the average and flatter the grid. It is dropped from
both numerator and denominator, which treats stored energy as carrying the
average intensity of the hour it is released in. Storage is around 1.6% of
generation, so the choice moves little either way — but it should be a choice
rather than an accident.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
CSV = HERE / "data" / "india-grid" / "india_psp_15min.csv"

#: IPCC AR5 lifecycle factors, gCO2eq/kWh. Same values as src/carbon.py.
FACTORS = {
    "nuclear_mw": 12.0,
    "wind_mw": 11.0,
    "solar_mw": 45.0,
    "hydro_mw": 24.0,
    "gas_mw": 490.0,
    "thermal_mw": 820.0,   # coal; see module docstring on lignite
    "others_mw": 700.0,    # biomass and assorted small generation
}


def load_15min() -> pd.DataFrame:
    if not CSV.exists():
        raise FileNotFoundError(f"{CSV} missing — run fetch_india_psp.py first")
    d = pd.read_csv(CSV, parse_dates=["timestamp"])
    return d.sort_values("timestamp").reset_index(drop=True)


def carbon_intensity(df: pd.DataFrame) -> pd.Series:
    """gCO2eq per kWh of generation, per 15-minute interval."""
    cols = [c for c in FACTORS if c in df.columns]
    gen = df[cols].apply(pd.to_numeric, errors="coerce")
    total = gen.sum(axis=1)
    weighted = sum(gen[c] * FACTORS[c] for c in cols)
    return (weighted / total.where(total > 0)).rename("ci")


def hourly(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Hourly carbon intensity, demand and renewable share.

    Averaged from the four 15-minute intervals in each hour rather than sampled,
    so a spike inside the hour cannot become the hour.
    """
    d = load_15min() if df is None else df.copy()
    d["ci"] = carbon_intensity(d)
    d = d.dropna(subset=["ci"])

    gen_cols = [c for c in FACTORS if c in d.columns]
    d["total_gen_mw"] = d[gen_cols].sum(axis=1)
    d["renewable_mw"] = d[["wind_mw", "solar_mw", "hydro_mw"]].sum(axis=1)

    d = d.set_index("timestamp")
    out = d.resample("1h").agg({
        "ci": "mean",
        "demand_met_mw": "mean",
        "total_gen_mw": "mean",
        "renewable_mw": "mean",
        "thermal_mw": "mean",
        "solar_mw": "mean",
        "wind_mw": "mean",
    }).dropna(subset=["ci"])
    out["renewable_share"] = out["renewable_mw"] / out["total_gen_mw"]
    return out.reset_index()


if __name__ == "__main__":
    h = hourly()
    print(f"{len(h):,} hourly rows · {h.timestamp.min():%Y-%m-%d} -> "
          f"{h.timestamp.max():%Y-%m-%d}\n")
    print(f"  carbon intensity  mean {h.ci.mean():.0f}  std {h.ci.std():.0f}  "
          f"p10 {h.ci.quantile(.1):.0f}  p90 {h.ci.quantile(.9):.0f} gCO2eq/kWh")
    print(f"  renewable share   mean {h.renewable_share.mean() * 100:.1f}%")

    by_hour = h.assign(hh=h.timestamp.dt.hour).groupby("hh")["ci"].mean()
    print(f"\n  cleanest hour {by_hour.idxmin():02d}:00 ({by_hour.min():.0f})  ·  "
          f"dirtiest {by_hour.idxmax():02d}:00 ({by_hour.max():.0f})  ·  "
          f"swing {by_hour.max() / by_hour.min():.2f}x")

    print("\n  mean intensity by hour (gCO2eq/kWh):")
    lo, hi = by_hour.min(), by_hour.max()
    for hh in range(24):
        v = by_hour.get(hh)
        if v is None:
            continue
        bar = "#" * int((v - lo) / max(hi - lo, 1e-9) * 34)
        print(f"    {hh:02d}  {v:6.0f}  {bar}")

    print("\n  Spain 267 · Germany 358 (hourly, ENTSO-E, same AR5 factors)")
