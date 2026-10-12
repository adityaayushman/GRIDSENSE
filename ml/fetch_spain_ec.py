"""Fetch a long Spanish generation record from Energy-Charts (Fraunhofer ISE).

The Kaggle ENTSO-E dataset behind the deployed forecaster ends in December 2018.
Energy-Charts republishes ENTSO-E generation by production type for Spain, free
and without an API key (CC BY 4.0), from 2015 to the present. That extends the
record from four years to eleven and, more usefully, reaches the grid as it is
now: solar has roughly tripled since 2018 and coal has nearly gone.

    python fetch_spain_ec.py            # 2015-01 .. last complete month
    python fetch_spain_ec.py --from 2024-01 --to 2024-03

Writes data/es-ec/spain_hourly.csv (UTC, hourly means of the 15-minute rows) and
derives carbon intensity with the same IPCC AR5 factors the rest of the project
uses (src/carbon.py maps the Kaggle names; the table below is the same factors
under Energy-Charts' names). Production types that are not generation —
pumped-storage consumption, cross-border trading, load and the derived shares —
are excluded, exactly as the Kaggle pipeline excludes consumption.

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
OUT = HERE / "data" / "es-ec" / "spain_hourly.csv"
RAW = HERE / "data" / "es-ec" / "raw"
API = "https://api.energy-charts.info/public_power"

# gCO2eq/kWh, lifecycle, IPCC AR5 WG3 Annex III — identical to src/carbon.py.
FACTORS = {
    "Biomass": 230.0,
    "Fossil hard coal": 820.0,
    "Fossil oil": 650.0,
    "Fossil gas": 490.0,
    "Hydro Run-of-River": 24.0,
    "Hydro water reservoir": 24.0,
    "Hydro pumped storage": 24.0,
    "Nuclear": 12.0,
    "Others": 700.0,
    "Other renewables": 100.0,
    "Waste": 700.0,
    "Wind onshore": 11.0,
    "Solar": 45.0,
}


def chunks(first: str, last: str):
    """Calendar years, clipped to the requested range: ~12 requests, not ~140."""
    y, m = map(int, first.split("-"))
    ly, lm = map(int, last.split("-"))
    while (y, m) <= (ly, lm):
        end_m = lm if y == ly else 12
        yield y, m, end_m
        y, m = y + 1, 1


def get(url: str) -> dict:
    """GET with backoff. The service is free and rate-limited; a 429 means wait, not fail."""
    for attempt in range(8):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
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


def fetch_chunk(y: int, m0: int, m1: int) -> pd.DataFrame:
    """One request per chunk, cached on disk so an interrupted run resumes."""
    start = date(y, m0, 1)
    end = date(y + (m1 == 12), 1 if m1 == 12 else m1 + 1, 1)
    cache = RAW / f"{start.isoformat()}_{end.isoformat()}.json"
    if cache.exists():
        d = json.loads(cache.read_text(encoding="utf-8"))
    else:
        q = urllib.parse.urlencode({"country": "es", "start": start.isoformat(), "end": end.isoformat()})
        d = get(f"{API}?{q}")
        RAW.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(d), encoding="utf-8")
        time.sleep(8)  # be polite to a free public service
    idx = pd.to_datetime(d["unix_seconds"], unit="s", utc=True)
    cols = {p["name"]: p["data"] for p in d["production_types"] if p["name"] in FACTORS or p["name"] == "Load"}
    return pd.DataFrame(cols, index=idx)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="first", default="2015-01")
    today = date.today()
    prev = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    ap.add_argument("--to", dest="last", default=f"{prev[0]}-{prev[1]:02d}")
    a = ap.parse_args()

    frames = []
    for y, m0, m1 in chunks(a.first, a.last):
        df = fetch_chunk(y, m0, m1)
        frames.append(df)
        print(f"  {y}-{m0:02d}..{m1:02d}: {len(df):,} rows", flush=True)

    raw = pd.concat(frames).sort_index()
    raw = raw[~raw.index.duplicated()]
    hourly = raw.resample("1h").mean()

    gen = hourly[[c for c in FACTORS if c in hourly.columns]].clip(lower=0).fillna(0.0)
    total = gen.sum(axis=1)
    hourly["ci"] = (sum(gen[c] * FACTORS[c] for c in gen.columns) / total.where(total > 0))
    hourly["total_gen_mw"] = total

    OUT.parent.mkdir(parents=True, exist_ok=True)
    hourly.to_csv(OUT)
    print(f"\n{len(hourly):,} hourly rows, {hourly.index.min():%Y-%m-%d} .. {hourly.index.max():%Y-%m-%d}")
    print(f"ci: mean {hourly.ci.mean():.0f}, missing {hourly.ci.isna().sum():,}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
