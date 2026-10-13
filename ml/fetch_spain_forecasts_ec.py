"""Spanish day-ahead solar, wind and load forecasts, and day-ahead prices, 2015 onward.

The deployed forecaster's strongest inputs are the TSO's day-ahead solar, wind and
load forecasts (finding 15: without them the share of the achievable saving
captured falls from 71% to 41%). The Kaggle record that supplied them stops in
December 2018, and ENTSO-E's own API needs a token. Energy-Charts (Fraunhofer ISE)
republishes the same ENTSO-E day-ahead series for Spain, free and without a key
(CC BY 4.0), so the modern grid can be modelled with the inputs that matter.

    python fetch_spain_forecasts_ec.py

Writes data/es-ec/spain_dayahead_hourly.csv (UTC, hourly means):
  fc_solar_mw, fc_wind_mw, fc_load_mw   day-ahead forecasts
  price_eur_mwh                          day-ahead market price (Spanish bidding zone)

The service rate-limits hard; requests are one per year per series, spaced out, and
a 429 is waited out rather than treated as failure. Responses are cached under
data/es-ec/raw_fc/, so an interrupted run resumes.

Data: Energy-Charts, Fraunhofer ISE, https://www.energy-charts.info (CC BY 4.0).
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
RAW = HERE / "data" / "es-ec" / "raw_fc"
OUT = HERE / "data" / "es-ec" / "spain_dayahead_hourly.csv"
API = "https://api.energy-charts.info/"

SERIES = {
    "fc_solar_mw": ("public_power_forecast", {"production_type": "solar", "forecast_type": "day-ahead"}, "forecast_values"),
    "fc_wind_mw": ("public_power_forecast", {"production_type": "wind_onshore", "forecast_type": "day-ahead"}, "forecast_values"),
    "fc_load_mw": ("public_power_forecast", {"production_type": "load", "forecast_type": "day-ahead"}, "forecast_values"),
    "price_eur_mwh": ("price", {"bzn": "ES"}, "price"),
}


def get(url: str) -> dict:
    for attempt in range(10):
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 9:
                raise
            wait = int(e.headers.get("Retry-After") or 0) or 45 * (attempt + 1)
            print(f"    429 - waiting {wait}s", flush=True)
            time.sleep(wait)
        except Exception:
            if attempt == 9:
                raise
            time.sleep(8 * (attempt + 1))
    raise RuntimeError("unreachable")


def fetch_year(name: str, year: int, last: date) -> pd.Series:
    path, params, key = SERIES[name]
    start, end = date(year, 1, 1), min(date(year + 1, 1, 1), last)
    cache = RAW / f"{name}_{year}.json"
    if cache.exists():
        d = json.loads(cache.read_text(encoding="utf-8"))
    else:
        q = urllib.parse.urlencode({"country": "es", **params, "start": start.isoformat(), "end": end.isoformat()})
        d = get(f"{API}{path}?{q}")
        RAW.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(d), encoding="utf-8")
        time.sleep(12)
    idx = pd.to_datetime(d["unix_seconds"], unit="s", utc=True)
    return pd.Series(d[key], index=idx, dtype="float64", name=name)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-year", type=int, default=2015)
    a = ap.parse_args()
    last = date.today()

    cols = {}
    for name in SERIES:
        parts = []
        for year in range(a.from_year, last.year + 1):
            s = fetch_year(name, year, last)
            parts.append(s)
            print(f"  {name:<14} {year}: {s.notna().sum():>6,} values", flush=True)
        cols[name] = pd.concat(parts)
    frame = pd.DataFrame({k: v[~v.index.duplicated()] for k, v in cols.items()}).sort_index()
    hourly = frame.resample("1h").mean()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    hourly.to_csv(OUT)
    print(f"\n{len(hourly):,} hourly rows {hourly.index.min():%Y-%m-%d}..{hourly.index.max():%Y-%m-%d}")
    print(hourly.notna().mean().round(3).to_string())
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
