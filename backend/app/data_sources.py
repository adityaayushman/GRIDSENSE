"""
Grid data providers.

Serves *measured* Spanish grid data: hourly carbon intensity derived from the
ENTSO-E generation mix, and hourly day-ahead market prices. Both come from
`app/data/grid_days.json`, built by `ml/export_grid_days.py` — see `ml/README.md`
for the derivation and its validation.

Each stored day is a 18:00->07:00 *charging night*, so indices 0-7 hold the
early hours of the following calendar day. That is the window an EV is actually
plugged in for, and it spans two dates.

Why Spain: it is one of the few countries where ordinary households are billed
at genuinely hourly-varying prices (the regulated PVPC tariff), which is the
premise the cost objective depends on.

ENTSO-E docs: https://transparency.entsoe.eu/
"""

import json
import os
from functools import lru_cache
from pathlib import Path

USE_LIVE_DATA = os.getenv("USE_LIVE_DATA", "false").lower() == "true"
ENTSOE_TOKEN = os.getenv("ENTSOE_TOKEN")

DATA_FILE = Path(__file__).parent / "data" / "grid_days.json"

# Spain's PVPC bill is an hourly energy term plus access tolls, levies and
# supplier margin that do not vary by hour. Charging can only shift the hourly
# part, so omitting this flat component would materially overstate the bill
# saving. Approximate 2018 residential value, EUR/kWh. Being flat, it does not
# change which hours the optimizer picks — only the reported percentage.
PVPC_FIXED_EUR_PER_KWH = 0.062

CURRENCY = "EUR"


@lru_cache(maxsize=1)
def _grid_data() -> dict:
    with DATA_FILE.open(encoding="utf-8") as fh:
        return json.load(fh)


def available_days() -> list[str]:
    """Sorted ISO dates for which a complete charging night is available."""
    return sorted(_grid_data()["days"])


def default_day() -> str:
    """The median-saving night, so the default view is representative."""
    return _grid_data()["default_day"]


def resolve_day(day: str | None) -> str:
    """Validate a requested day, falling back to the representative default."""
    if day is None:
        return default_day()
    if day not in _grid_data()["days"]:
        raise ValueError(
            f"No grid data for {day}. Available: {available_days()[0]}..{available_days()[-1]}"
        )
    return day


def get_carbon_intensity(region: str = "ES", day: str | None = None) -> list[float]:
    """Measured grid carbon intensity, gCO2eq/kWh, for each hour 0-23."""
    if USE_LIVE_DATA and ENTSOE_TOKEN:
        return _fetch_live(region)
    return list(_grid_data()["days"][resolve_day(day)]["carbon"])


def get_price(region: str = "ES", day: str | None = None) -> list[float]:
    """Retail price in EUR/kWh for each hour 0-23.

    Day-ahead wholesale price plus the flat PVPC access component — see
    `PVPC_FIXED_EUR_PER_KWH`.
    """
    hourly = _grid_data()["days"][resolve_day(day)]["price"]
    return [round(p + PVPC_FIXED_EUR_PER_KWH, 5) for p in hourly]


def get_residential_baseline_kw(household_count: int = 1) -> list[float]:
    """Synthetic residential demand curve (kW), scaled per household.

    Still synthetic: the ENTSO-E feed reports system-wide load, not the
    residential share behind a single distribution feeder, so it cannot be
    scaled down to a neighbourhood without an assumption. Shaped as a morning
    and an evening peak, which is the standard residential profile.
    """
    import math

    return [
        round(
            household_count
            * (2.2 + 1.8 * math.exp(-((h - 19) ** 2) / 8) + 0.6 * math.exp(-((h - 8) ** 2) / 4)),
            2,
        )
        for h in range(24)
    ]


def _fetch_live(region: str) -> list[float]:  # pragma: no cover - network call
    """Live carbon intensity from ENTSO-E.

    Previously this called WattTime, which covers North American balancing
    authorities — enabling it against a Spanish grid would have mixed
    continents. ENTSO-E is the source the bundled data came from, so live and
    offline series are derived identically. See app/entsoe.py.
    """
    from app.entsoe import fetch_carbon_intensity

    return fetch_carbon_intensity(region)
