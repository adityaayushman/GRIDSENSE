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


def get_carbon_forecast(region: str = "ES", day: str | None = None) -> list[float] | None:
    """The day-ahead prediction for this night, or None if the night has none.

    Precomputed by ml/export_forecast_curves.py from the deployed ridge model,
    so serving it needs no ML dependency here.
    """
    return _grid_data()["days"][resolve_day(day)].get("carbon_forecast")


def forecast_meta() -> dict:
    """Model provenance for the forecast curves, for the UI to cite."""
    return _grid_data().get("forecast", {})


def get_price(region: str = "ES", day: str | None = None) -> list[float]:
    """Retail price in EUR/kWh for each hour 0-23.

    Day-ahead wholesale price plus the flat PVPC access component — see
    `PVPC_FIXED_EUR_PER_KWH`.
    """
    hourly = _grid_data()["days"][resolve_day(day)]["price"]
    return [round(p + PVPC_FIXED_EUR_PER_KWH, 5) for p in hourly]


#: Mean Spanish system load by local hour, normalised to a mean of 1.0.
#:
#: Derived from 35,056 measured hours of ENTSO-E `total load actual`
#: (2015-2018), converted to Europe/Madrid. Baked in as constants rather than
#: read from a file for the same reason the forecaster ships as coefficients:
#: the serverless bundle stays free of data files and of pandas.
SPAIN_LOAD_SHAPE = [
    0.9160, 0.8569, 0.8173, 0.7986, 0.7913, 0.8016,
    0.8562, 0.9395, 1.0051, 1.0604, 1.0975, 1.1115,
    1.1177, 1.1214, 1.0944, 1.0672, 1.0555, 1.0562,
    1.0707, 1.0914, 1.1132, 1.1187, 1.0616, 0.9798,
]

#: IDAE puts the average Spanish household at ~3,487 kWh a year.
SPAIN_DAILY_KWH_PER_HOME = 3487 / 365


def get_residential_baseline_kw(household_count: int = 1) -> list[float]:
    """Residential feeder demand (kW), measured in both shape and magnitude.

    This curve was previously a pair of hand-drawn Gaussians. Its shape was the
    documented assumption; its *magnitude* was never checked, and it turned out
    to imply 1,915 kWh per household per month against a measured Spanish
    average near 291 — a sevenfold overstatement that inflated every hosting
    capacity figure derived from it. See finding 11.

    Now the shape comes from measured system load and the level from measured
    household consumption, so only one thing is still assumed.

    **That assumption is that a residential feeder follows system demand.** It
    does not exactly: system load carries industry, which runs flat around the
    clock, so a system-shaped profile is *less peaky* than a real street. This
    understates the evening residential peak, which means it overstates the
    headroom left for charging. Hosting capacity computed against it should be
    read as an upper bound. Closing that needs metered feeder data, which no
    open Spanish source publishes.
    """
    scale = SPAIN_DAILY_KWH_PER_HOME / sum(SPAIN_LOAD_SHAPE)
    return [round(household_count * s * scale, 3) for s in SPAIN_LOAD_SHAPE]


def _fetch_live(region: str) -> list[float]:  # pragma: no cover - network call
    """Live carbon intensity from ENTSO-E.

    Previously this called WattTime, which covers North American balancing
    authorities — enabling it against a Spanish grid would have mixed
    continents. ENTSO-E is the source the bundled data came from, so live and
    offline series are derived identically. See app/entsoe.py.
    """
    from app.entsoe import fetch_carbon_intensity

    return fetch_carbon_intensity(region)
