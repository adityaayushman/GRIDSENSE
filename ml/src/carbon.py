"""Derive grid carbon intensity from a generation-by-fuel mix.

The Kaggle ENTSO-E dataset gives hourly generation in MW per fuel type. Carbon
intensity is that mix weighted by per-fuel lifecycle emission factors — the same
construction ElectricityMaps uses for its published intensities.

Emission factors are gCO2eq/kWh, lifecycle (construction + fuel + operation),
taken from IPCC AR5 WG3 Annex III median values, which is also what
ElectricityMaps uses as its default set.

IMPORTANT — average vs. marginal
--------------------------------
This yields *average* carbon intensity: the emissions of the average kWh on the
grid right now. GridSense's premise is *marginal* emissions (WattTime's MOER):
the emissions of the *next* kWh, which is what actually changes when you move a
charging load. They are not the same number, and shifting load responds to the
marginal rate.

`estimate_marginal_intensity` derives a marginal estimate from the same data by
regressing hourly change in total emissions against hourly change in load — the
standard empirical approach when MOER is not directly published. Both are
returned so downstream code can be explicit about which one it uses.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# gCO2eq/kWh, lifecycle. IPCC AR5 WG3 Annex III medians.
EMISSION_FACTORS: dict[str, float] = {
    "generation biomass": 230.0,
    "generation fossil brown coal/lignite": 1054.0,
    "generation fossil coal-derived gas": 820.0,
    "generation fossil gas": 490.0,
    "generation fossil hard coal": 820.0,
    "generation fossil oil": 650.0,
    "generation fossil oil shale": 1000.0,
    "generation fossil peat": 1000.0,
    "generation geothermal": 38.0,
    "generation hydro pumped storage aggregated": 24.0,
    "generation hydro run-of-river and poundage": 24.0,
    "generation hydro water reservoir": 24.0,
    "generation marine": 17.0,
    "generation nuclear": 12.0,
    "generation other": 700.0,  # unspecified thermal; assumed fossil-like
    "generation other renewable": 100.0,
    "generation solar": 45.0,
    "generation waste": 700.0,
    "generation wind offshore": 11.0,
    "generation wind onshore": 11.0,
}

# Not generation — this is energy *consumed* to fill pumped storage. Including it
# as supply would double-count, since it is re-served later as pumped-storage
# generation.
EXCLUDED_COLUMNS = ("generation hydro pumped storage consumption",)


def carbon_intensity(df: pd.DataFrame) -> pd.Series:
    """Average grid carbon intensity in gCO2eq/kWh, per row.

    Returns NaN for hours with no reported generation rather than 0, so that
    missing data is never mistaken for a perfectly clean grid.
    """
    cols = [c for c in EMISSION_FACTORS if c in df.columns]
    generation = df[cols].fillna(0.0)

    total_mw = generation.sum(axis=1)
    weighted = sum(generation[c] * EMISSION_FACTORS[c] for c in cols)

    intensity = weighted / total_mw.replace(0.0, np.nan)
    intensity.name = "carbon_intensity"
    return intensity


def total_emissions_t_per_h(df: pd.DataFrame) -> pd.Series:
    """Absolute grid emissions in tonnes CO2eq per hour."""
    cols = [c for c in EMISSION_FACTORS if c in df.columns]
    generation = df[cols].fillna(0.0)
    # MW * gCO2/kWh = g/h * 1e3 -> t/h needs /1e6, so net factor is 1e-3
    grams_per_hour = sum(generation[c] * EMISSION_FACTORS[c] for c in cols) * 1e3
    return grams_per_hour / 1e6


def estimate_marginal_intensity(df: pd.DataFrame, load_col: str = "total load actual") -> float:
    """Estimate a single system marginal emission rate in gCO2eq/kWh.

    Regresses hour-over-hour change in total emissions on change in load. The
    slope is the emission rate of whichever plant is following load — the
    marginal unit. Differencing removes the slow-moving level effects (seasonal
    capacity, fuel prices) that otherwise dominate a levels regression.
    """
    emissions_t = total_emissions_t_per_h(df)  # t/h
    load_mw = df[load_col]

    d_emissions = emissions_t.diff() * 1e6  # -> grams
    d_load = load_mw.diff() * 1e3  # MW -> kWh over one hour

    mask = d_emissions.notna() & d_load.notna() & (d_load.abs() > 1e-6)
    if mask.sum() < 2:
        raise ValueError("Not enough paired observations to estimate a marginal rate")

    slope, _ = np.polyfit(d_load[mask], d_emissions[mask], 1)
    return float(slope)
