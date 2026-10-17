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

DATA_DIR = Path(__file__).parent / "data"

#: The grid in two eras. 2018 is the original served year, backed by the Kaggle ENTSO-E
#: record. 2025 is the grid as it is now (mean intensity roughly half of 2018's, solar
#: roughly three times), built by ml/export_grid_days_modern.py.
ERA_FILES = {"2018": DATA_DIR / "grid_days.json", "2025": DATA_DIR / "grid_days_2025.json",
             "IN": DATA_DIR / "grid_days_in.json"}
DEFAULT_ERA = "2018"
DATA_FILE = ERA_FILES[DEFAULT_ERA]   # kept for importers that predate eras

# Spain's PVPC bill is an hourly energy term plus access tolls, levies and
# supplier margin that do not vary by hour. Charging can only shift the hourly
# part, so omitting this flat component would materially overstate the bill
# saving. Approximate 2018 residential value, EUR/kWh. Being flat, it does not
# change which hours the optimizer picks — only the reported percentage.
PVPC_FIXED_EUR_PER_KWH = 0.062

CURRENCY = "EUR"


def eras() -> list[str]:
    return [e for e, path in ERA_FILES.items() if path.exists()]


@lru_cache(maxsize=4)
def _grid_data(era: str = DEFAULT_ERA) -> dict:
    if era not in ERA_FILES or not ERA_FILES[era].exists():
        raise ValueError(f"No grid data for era {era!r}. Available: {eras()}")
    with ERA_FILES[era].open(encoding="utf-8") as fh:
        return json.load(fh)


def year_stats(era: str = DEFAULT_ERA) -> dict:
    """Whole-year saving statistics for the era, for the UI to quote beside a single night."""
    return _grid_data(era).get("year_stats") or {}


def available_days(era: str = DEFAULT_ERA) -> list[str]:
    """Sorted ISO dates for which a complete charging night is available."""
    return sorted(_grid_data(era)["days"])


def default_day(era: str = DEFAULT_ERA) -> str:
    """The median-saving night, so the default view is representative."""
    return _grid_data(era)["default_day"]


def resolve_day(day: str | None, era: str = DEFAULT_ERA) -> str:
    """Validate a requested day, falling back to the representative default."""
    if day is None:
        return default_day(era)
    if day not in _grid_data(era)["days"]:
        days = available_days(era)
        raise ValueError(f"No grid data for {day} in {era}. Available: {days[0]}..{days[-1]}")
    return day


def get_carbon_intensity(region: str = "ES", day: str | None = None, era: str = DEFAULT_ERA) -> list[float]:
    """Measured grid carbon intensity, gCO2eq/kWh, for each hour 0-23."""
    if USE_LIVE_DATA and ENTSOE_TOKEN and era != "IN":
        return _fetch_live(region)
    return list(_grid_data(era)["days"][resolve_day(day, era)]["carbon"])


def get_carbon_forecast(region: str = "ES", day: str | None = None, era: str = DEFAULT_ERA) -> list[float] | None:
    """The day-ahead prediction for this night, or None if the night has none.

    Precomputed by ml/export_forecast_curves.py from the deployed ridge model,
    so serving it needs no ML dependency here.
    """
    return _grid_data(era)["days"][resolve_day(day, era)].get("carbon_forecast")


def forecast_meta(era: str = DEFAULT_ERA) -> dict:
    """Model provenance for the forecast curves, for the UI to cite."""
    return _grid_data(era).get("forecast", {})


def get_price(region: str = "ES", day: str | None = None, era: str = DEFAULT_ERA) -> list[float]:
    """Retail price in EUR/kWh for each hour 0-23.

    Day-ahead wholesale price plus the flat PVPC access component — see
    `PVPC_FIXED_EUR_PER_KWH`.
    """
    data = _grid_data(era)
    hourly = data["days"][resolve_day(day, era)]["price"]
    if data.get("price_includes_fixed"):          # the Indian curve is already a full tariff
        return [round(p, 5) for p in hourly]
    return [round(p + PVPC_FIXED_EUR_PER_KWH, 5) for p in hourly]


def currency(era: str = DEFAULT_ERA) -> str:
    return _grid_data(era).get("currency", CURRENCY)


def region_of(era: str = DEFAULT_ERA) -> str:
    return _grid_data(era).get("region", "ES")


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


def get_residential_baseline_kw(household_count: int = 1, era: str = DEFAULT_ERA) -> list[float]:
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
    own = _grid_data(era).get("residential_baseline_kw_per_home")
    if own:                                      # an era that ships its own baseline (India)
        return [round(household_count * v, 3) for v in own]
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
