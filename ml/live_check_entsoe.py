"""Live check of the ENTSO-E client against an independent copy of the same data.

`backend/app/entsoe.py` has been tested against recorded fixtures but never
against the real endpoint, because that needs a security token. With one, this
settles it in a single command by fetching a recent Spanish day through the client
and comparing it, hour by hour, with the same day from Energy-Charts, which
republishes ENTSO-E generation independently of this project's code.

    set ENTSOE_TOKEN=...   (PowerShell: $env:ENTSOE_TOKEN = "...")
    python live_check_entsoe.py                 # three days ago
    python live_check_entsoe.py --day 2026-10-01

What passing means, and does not: the client's request, XML parsing, resolution
handling and emission factors agree with an independent source to within a few
percent. Both read ENTSO-E, so it cannot catch an error ENTSO-E itself makes.

Exit status: 0 pass, 1 fail, 2 no token.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend"))

from app.entsoe import EntsoeError, fetch_carbon_intensity  # noqa: E402
from fetch_spain_ec import FACTORS  # noqa: E402

#: Hourly mean absolute difference, gCO2eq/kWh, allowed between the two sources.
MAE_LIMIT = 15.0
CORR_LIMIT = 0.97

HOW_TO_GET_A_TOKEN = """\
No ENTSOE_TOKEN is set. To get one (free):

  1. Register at https://transparency.entsoe.eu (top right, "Login" -> "Register").
  2. Email transparency@entsoe.eu with the subject "Restful API access" and the
     address you registered with in the body.
  3. When they reply, the token is under My Account Settings -> Web API Security Token.

Then set it and re-run this script. See backend/ENTSOE.md for a ready-to-send email.
"""


def energy_charts_day(day: datetime) -> list[float]:
    """The same UTC day from Energy-Charts, as carbon intensity by hour 0-23."""
    start = day.date()
    end = start + timedelta(days=1)
    url = f"https://api.energy-charts.info/public_power?country=es&start={start}&end={end}"
    with urllib.request.urlopen(url, timeout=90) as r:
        d = json.load(r)
    import pandas as pd

    idx = pd.to_datetime(d["unix_seconds"], unit="s", utc=True)
    cols = {p["name"]: p["data"] for p in d["production_types"] if p["name"] in FACTORS}
    gen = pd.DataFrame(cols, index=idx).clip(lower=0).fillna(0.0)
    gen = gen[gen.index.date == start].resample("1h").mean()
    total = gen.sum(axis=1)
    ci = sum(gen[c] * FACTORS[c] for c in gen.columns) / total.where(total > 0)
    return [round(float(ci.get(pd.Timestamp(f"{start} {h:02d}:00", tz="UTC"), float("nan"))), 1) for h in range(24)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", help="UTC date, YYYY-MM-DD (default: three days ago)")
    a = ap.parse_args()

    token = os.getenv("ENTSOE_TOKEN")
    if not token:
        print(HOW_TO_GET_A_TOKEN)
        return 2

    day = (datetime.strptime(a.day, "%Y-%m-%d").replace(tzinfo=timezone.utc) if a.day
           else datetime.now(timezone.utc) - timedelta(days=3))
    print(f"checking {day:%Y-%m-%d} (UTC)")

    try:
        client = fetch_carbon_intensity("ES", token=token, day=day)
    except EntsoeError as e:
        print(f"FAIL: the client raised: {e}")
        return 1
    ref = energy_charts_day(day)

    pairs = [(h, c, r) for h, (c, r) in enumerate(zip(client, ref)) if r == r]
    if len(pairs) < 20:
        print(f"FAIL: only {len(pairs)} comparable hours")
        return 1
    mae = sum(abs(c - r) for _, c, r in pairs) / len(pairs)
    mc, mr = sum(c for _, c, _ in pairs) / len(pairs), sum(r for _, _, r in pairs) / len(pairs)
    cov = sum((c - mc) * (r - mr) for _, c, r in pairs)
    corr = cov / ((sum((c - mc) ** 2 for _, c, _ in pairs) * sum((r - mr) ** 2 for _, _, r in pairs)) ** 0.5 or 1)

    print(f"{'hour':>5} {'client':>8} {'energy-charts':>14} {'diff':>7}")
    for h, c, r in pairs:
        print(f"{h:>5} {c:>8.1f} {r:>14.1f} {c - r:>+7.1f}")
    ok = mae <= MAE_LIMIT and corr >= CORR_LIMIT
    print(f"\nmean abs difference {mae:.1f} g/kWh (limit {MAE_LIMIT}) · correlation {corr:.3f} (limit {CORR_LIMIT})")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
