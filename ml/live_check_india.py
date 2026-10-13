"""Live check of the Indian carbon feed. Free, no key, about three seconds.

India is this project's main focus, and its live source needs no account: Grid-India
publishes yesterday's all-India generation by fuel every morning. This runs the
production provider (`backend/app/india_live.py`) against the real portal and checks
five things, each of which has failed for real at some point:

  1. REACHABLE  the portal answers and a report can be downloaded and read;
  2. FRESH      it describes yesterday or the day before, not a stale file;
  3. PLAUSIBLE  solar is zero at night and the fuels sum to the sheet's own total
                (the checks that would have caught the parser error of finding 14);
  4. AGREES     the backend's xlrd parser and the ML pipeline's pandas parser, two
                independent implementations, give the same hourly intensity from the
                same bytes;
  5. FAST       the whole thing, uncached, finishes in under ten seconds.

    python live_check_india.py

Exit status: 0 pass, 1 fail. It cannot catch an error Grid-India itself makes in the
report, and "live" means the newest day the publisher offers, about a day old.
"""

from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

import httpx

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend"))

from app import india_live  # noqa: E402

MAX_SECONDS = 10.0
MAX_PARSER_DISAGREEMENT = 0.2      # g/kWh


def pandas_hourly_ci(path: Path, day: date) -> list[float]:
    """The ML pipeline's own parser, run on the same file, reduced to hourly intensity."""
    import pandas as pd

    from fetch_india_psp import parse

    frame = parse(path, day)
    if frame is None:
        raise RuntimeError("the pandas parser rejected the file the backend accepted")
    frame = frame.set_index("timestamp")
    hourly = frame.resample("1h").mean()
    gen = hourly[list(india_live.FACTORS)]
    return [round(float(v), 1) for v in (sum(gen[c] * india_live.FACTORS[c] for c in gen.columns) / gen.sum(axis=1))]


def main() -> int:
    problems: list[str] = []
    t0 = time.time()
    india_live._latest = None
    india_live._days.clear()
    with httpx.Client(timeout=30.0, headers={"User-Agent": india_live.UA}, follow_redirects=True) as client:
        try:
            files = india_live._listing(client, date.today())
            if not files:
                prev = date.today().replace(day=1) - __import__("datetime").timedelta(days=1)
                files = india_live._listing(client, prev)
            stamp, path = max(files)
            blob = client.get(india_live.CDN + path)
            blob.raise_for_status()
        except (httpx.HTTPError, ValueError) as e:
            print(f"FAIL  REACHABLE  {type(e).__name__}: {e}")
            return 1
        try:
            day = india_live.latest_day(client=client)
        except india_live.IndiaLiveError as e:
            print(f"FAIL  PLAUSIBLE/READABLE  {e}")
            return 1
    elapsed = time.time() - t0
    s = day.summary()

    # 2. fresh
    if not s["fresh"]:
        problems.append(f"FRESH: newest report is {s['age_days']} days old ({s['day']})")
    # 3. plausible
    if not s["checks"]["plausible"]:
        problems.append(f"PLAUSIBLE: {s['checks']}")
    # 4. two independent parsers agree
    tmp = Path(__file__).parent / "data" / "india-psp" / "raw" / f"{stamp:%Y-%m-%d}.xls"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(blob.content)
    ref = pandas_hourly_ci(tmp, stamp)
    diff = max(abs(a - b) for a, b in zip(ref, day.carbon_intensity))
    if diff > MAX_PARSER_DISAGREEMENT:
        problems.append(f"AGREES: the two parsers differ by up to {diff:.1f} g/kWh")
    # 5. fast
    if elapsed > MAX_SECONDS:
        problems.append(f"FAST: took {elapsed:.1f}s (limit {MAX_SECONDS}s)")

    print(f"day {s['day']} · {s['age_days']} day(s) old · mean {s['mean_carbon_intensity']} g/kWh · "
          f"cleanest {s['cleanest_hour']:02d}:00, dirtiest {s['dirtiest_hour']:02d}:00")
    print(f"checks: solar zero at night {s['checks']['solar_zero_at_night']}, fuels sum to total "
          f"{s['checks']['fuels_sum_to_total']} (median gap {s['checks']['median_closure_gap_pct']}%)")
    print(f"parsers: xlrd (backend) vs pandas (ML) differ by at most {diff:.2f} g/kWh over 24 hours")
    print(f"elapsed: {elapsed:.1f}s uncached")
    print(f"{'hour':>5} {'g/kWh':>8} {'demand MW':>10} {'renewable %':>12}")
    for h in s["hourly"][::3]:
        print(f"{h['hour']:>5} {h['carbon_intensity']:>8} {h['demand_met_mw']:>10,} {h['renewable_share_pct']:>12}")
    if problems:
        print("\nFAIL")
        for p in problems:
            print("  -", p)
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
