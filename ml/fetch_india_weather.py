"""Hourly historical weather for 13 Indian cities, from Open-Meteo.

Indian grid demand is weather-driven (air conditioning above all) and so is a
growing share of its supply: solar output follows irradiance and cloud, wind
follows wind speed. A carbon or demand forecaster for India that ignores weather
leaves its two largest drivers on the table. Open-Meteo's archive serves ERA5
reanalysis hourly back to 1940, free and without a key (CC BY 4.0 for the data).

The cities are spread across the five regional grids and weighted toward demand
and installed solar/wind: Delhi, Lucknow, Jaipur and Jodhpur (north, with
Rajasthan's solar belt), Ahmedabad, Mumbai, Pune and Nagpur (west), Kolkata and
Bhubaneswar (east), Chennai, Bengaluru and Hyderabad (south).

    python fetch_india_weather.py                  # 2018-04-01 .. a week ago
    python fetch_india_weather.py --from 2025-01-01

Writes data/india-big/weather_hourly.csv, UTC, one column per city and variable
plus national means. Responses are cached under data/india-big/weather_raw/.

Weather: Open-Meteo.com (ERA5 reanalysis, Copernicus / ECMWF), CC BY 4.0.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
BIG = HERE / "data" / "india-big"
RAW = BIG / "weather_raw"
OUT = BIG / "weather_hourly.csv"
API = "https://archive-api.open-meteo.com/v1/archive"

CITIES = {
    "delhi": (28.61, 77.21), "lucknow": (26.85, 80.95), "jaipur": (26.91, 75.79),
    "jodhpur": (26.24, 73.02), "ahmedabad": (23.02, 72.57), "mumbai": (19.08, 72.88),
    "pune": (18.52, 73.86), "nagpur": (21.15, 79.09), "kolkata": (22.57, 88.36),
    "bhubaneswar": (20.30, 85.82), "chennai": (13.08, 80.27), "bengaluru": (12.97, 77.59),
    "hyderabad": (17.38, 78.48),
}
VARS = {
    "temperature_2m": "temp_c", "relative_humidity_2m": "rh_pct", "cloud_cover": "cloud_pct",
    "shortwave_radiation": "ghi_wm2", "wind_speed_10m": "wind_kmh", "precipitation": "rain_mm",
}


def get(url: str) -> dict:
    for attempt in range(8):
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 7:
                raise
            wait = int(e.headers.get("Retry-After") or 0) or 30 * (attempt + 1)
            print(f"    429 - waiting {wait}s", flush=True)
            time.sleep(wait)
        except Exception:
            if attempt == 7:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def fetch_city(name: str, lat: float, lon: float, start: str, end: str) -> pd.DataFrame:
    cache = RAW / f"{name}_{start}_{end}.json"
    if cache.exists():
        d = json.loads(cache.read_text(encoding="utf-8"))
    else:
        q = urllib.parse.urlencode({
            "latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
            "hourly": ",".join(VARS), "timezone": "UTC",
        })
        d = get(f"{API}?{q}")
        RAW.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(d), encoding="utf-8")
        time.sleep(5)
    h = d["hourly"]
    idx = pd.to_datetime(h["time"], utc=True)
    return pd.DataFrame({f"{name}_{short}": h[long] for long, short in VARS.items()}, index=idx)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="2018-04-01")
    ap.add_argument("--to", dest="end", default=(date.today() - timedelta(days=7)).isoformat())
    a = ap.parse_args()

    frames = []
    for name, (lat, lon) in CITIES.items():
        df = fetch_city(name, lat, lon, a.start, a.end)
        frames.append(df)
        print(f"  {name:<12} {len(df):,} hourly rows", flush=True)

    wide = pd.concat(frames, axis=1).sort_index()
    for short in VARS.values():
        cols = [f"{c}_{short}" for c in CITIES]
        # Rain is summed across cities (national wetness); everything else averaged.
        wide[f"india_{short}"] = wide[cols].sum(axis=1) if short == "rain_mm" else wide[cols].mean(axis=1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wide.to_csv(OUT)
    print(f"\n{len(wide):,} rows x {wide.shape[1]} columns, {wide.index.min():%Y-%m-%d}..{wide.index.max():%Y-%m-%d}")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
