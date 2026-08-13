"""
Grid data providers.

For now this returns a realistic synthetic 24h curve so the system runs
end-to-end without API keys. Swap `get_carbon_intensity` for a real
WattTime / ElectricityMaps call once you have credentials — see README.

WattTime docs:        https://www.watttime.org/api-documentation/
ElectricityMaps docs: https://docs.electricitymaps.com/
"""

import math
import os

import httpx

USE_LIVE_DATA = os.getenv("USE_LIVE_DATA", "false").lower() == "true"
WATTTIME_TOKEN = os.getenv("WATTTIME_TOKEN")


def get_carbon_intensity(region: str = "CAISO") -> list[float]:
    """Returns gCO2/kWh for each hour 0-23."""
    if USE_LIVE_DATA and WATTTIME_TOKEN:
        return _fetch_watttime(region)
    return _synthetic_carbon_curve()


def get_price(region: str = "CAISO") -> list[float]:
    """Returns retail price ($/kWh) for each hour 0-23.

    Modeled on PG&E's EV2-A time-of-use rate (the tariff most California EV
    owners are on), which is a step function rather than a smooth curve:

        00:00-15:00  off-peak
        15:00-16:00  part-peak
        16:00-21:00  peak
        21:00-24:00  part-peak

    Note this peaks at 16-21h, overlapping but not identical to the marginal
    emissions peak — which is why "min cost" and "min emissions" produce
    different schedules.
    """
    off_peak, part_peak, peak = 0.31, 0.51, 0.62
    return [
        peak if 16 <= h < 21 else part_peak if h == 15 or h >= 21 else off_peak
        for h in range(24)
    ]


def get_residential_baseline_kw(household_count: int = 1) -> list[float]:
    """Synthetic residential demand curve (kW), scaled per household.
    Replace with real utility load data (e.g. EIA, local utility open data)
    when available."""
    return [
        round(
            household_count
            * (2.2 + 1.8 * math.exp(-((h - 19) ** 2) / 8) + 0.6 * math.exp(-((h - 8) ** 2) / 4)),
            2,
        )
        for h in range(24)
    ]


def _synthetic_carbon_curve() -> list[float]:
    return [
        round(320 + 180 * math.exp(-((h - 19) ** 2) / 6) - 90 * math.exp(-((h - 13) ** 2) / 10), 1)
        for h in range(24)
    ]


def _fetch_watttime(region: str) -> list[float]:  # pragma: no cover - network call
    """Example live fetch — adapt to WattTime's forecast endpoint & auth flow."""
    headers = {"Authorization": f"Bearer {WATTTIME_TOKEN}"}
    resp = httpx.get(
        "https://api.watttime.org/v3/forecast",
        params={"region": region, "signal_type": "co2_moer"},
        headers=headers,
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    # NOTE: reshape according to WattTime's actual response schema
    return [point["value"] for point in data["data"]][:24]
