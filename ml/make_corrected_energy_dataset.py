"""Rebuild the Spanish ENTSO-E record from a source that agrees with Spain's grid operator.

The Kaggle dataset (`nicholasjhana/energy-consumption-generation-prices-and-weather`)
that this project's Spanish results were built on is wrong for roughly the first twelve
days of every month. Checked against Red Eléctrica de España's own published daily
generation (REE, the Spanish TSO) across 2017-2018:

    median gap to REE, total generation     days 1-12     days 13+
    Kaggle                                    11.1%          5.5%
    Energy-Charts                              7.2%          7.1%

(Energy-Charts sits a constant ~7% under REE on both, because REE's total counts
cogeneration and other items Energy-Charts does not carry; what matters is that it is
*flat* across the month. Kaggle's error doubles in the first twelve days, with outliers
such as wind on 2 June 2017: Kaggle 280 GWh, Energy-Charts 79, REE 81.) On days 13+ the
two copies are identical to the unit; on days 1-12 they differ, and Energy-Charts is the
one that tracks REE. FINDINGS.md finding 17.

This writes `data/raw/energy_dataset.csv` in the *same schema* as the Kaggle file, built
from Energy-Charts (a republication of ENTSO-E data, CC BY 4.0), so every existing script
runs unchanged. The original is kept beside it as `energy_dataset_kaggle.csv`.

    python make_corrected_energy_dataset.py

Needs `fetch_spain_ec.py` and `fetch_spain_forecasts_ec.py` to have been run first.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
RAW = HERE / "data" / "raw"
KAGGLE = RAW / "energy_dataset.csv"
KEEP = RAW / "energy_dataset_kaggle.csv"
EC = HERE / "data" / "es-ec"

#: Kaggle column -> Energy-Charts column. Spain has no lignite or coal-derived gas, so
#: those Kaggle columns are zero rather than missing.
GENERATION = {
    "generation biomass": "Biomass",
    "generation fossil gas": "Fossil gas",
    "generation fossil hard coal": "Fossil hard coal",
    "generation fossil oil": "Fossil oil",
    "generation hydro pumped storage aggregated": "Hydro pumped storage",
    "generation hydro run-of-river and poundage": "Hydro Run-of-River",
    "generation hydro water reservoir": "Hydro water reservoir",
    "generation nuclear": "Nuclear",
    "generation other": "Others",
    "generation other renewable": "Other renewables",
    "generation solar": "Solar",
    "generation waste": "Waste",
    "generation wind onshore": "Wind onshore",
}
ZERO = ["generation fossil brown coal/lignite", "generation fossil coal-derived gas", "generation fossil oil shale",
        "generation fossil peat", "generation geothermal", "generation marine", "generation wind offshore"]


def main() -> None:
    if not KEEP.exists():
        shutil.copy2(KAGGLE, KEEP)          # keep the original, once
    original = pd.read_csv(KEEP, parse_dates=["time"])
    original["time"] = pd.to_datetime(original["time"], utc=True)
    span = (original["time"].min(), original["time"].max())

    gen = pd.read_csv(EC / "spain_hourly.csv", index_col=0, parse_dates=True)
    fc = pd.read_csv(EC / "spain_dayahead_hourly.csv", index_col=0, parse_dates=True)
    gen.index, fc.index = pd.to_datetime(gen.index, utc=True), pd.to_datetime(fc.index, utc=True)
    idx = pd.date_range(span[0], span[1], freq="h", tz="UTC")

    out = pd.DataFrame(index=idx)
    for k, e in GENERATION.items():
        out[k] = gen[e].reindex(idx).clip(lower=0)
    for k in ZERO:
        out[k] = 0.0
    out["forecast solar day ahead"] = fc["fc_solar_mw"].reindex(idx)
    out["forecast wind onshore day ahead"] = fc["fc_wind_mw"].reindex(idx)
    out["total load forecast"] = fc["fc_load_mw"].reindex(idx)
    out["total load actual"] = gen["Load"].reindex(idx)
    out["price day ahead"] = fc["price_eur_mwh"].reindex(idx)
    out["price actual"] = fc["price_eur_mwh"].reindex(idx)
    out = out.interpolate(limit=3)
    out.index.name = "time"
    out.reset_index().assign(time=lambda d: d["time"].dt.strftime("%Y-%m-%d %H:%M:%S%z").str.replace(r"(\d{2})(\d{2})$", r"\1:\2", regex=True)).to_csv(KAGGLE, index=False)

    # How the two compare where they should agree (days 13+) and where they should not.
    o = original.drop_duplicates("time").set_index("time")
    gcol = "generation nuclear"
    j = pd.concat([o[gcol].rename("k"), out[gcol].rename("e")], axis=1, join="inner").dropna()
    late = j[j.index.day > 12]
    print(f"wrote {KAGGLE.name}: {len(out):,} hourly rows {out.index.min():%Y-%m-%d}..{out.index.max():%Y-%m-%d}")
    print(f"days 13+: {((late.k - late.e).abs() < 1).mean() * 100:.1f}% of nuclear hours identical to the original")
    gaps = out.drop(columns=["generation hydro pumped storage aggregated"]).isna().any(axis=1).sum()
    print(f"hours with any gap after interpolation (pumped storage is empty in both sources): {int(gaps)}")
    print(f"original preserved as {KEEP.name}")


if __name__ == "__main__":
    main()
