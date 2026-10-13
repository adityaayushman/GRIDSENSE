"""The statistics the findings quote that depend on the Spanish record, recomputed on the corrected one.

Run once after `make_corrected_energy_dataset.py` and the pipeline:

    python corrected_stats.py

It prints what FINDINGS.md quotes in findings 2, 5, 6, 7 and 8, so each number in the text has a
single source. Nothing here writes to the app.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "src"))
sys.path.insert(0, str(HERE.parent / "backend"))

from carbon import carbon_intensity  # noqa: E402
from spread_gate import NAIVE, emis, fill  # noqa: E402

WINDOW = [h % 24 for h in range(18, 31)]


def curves(frame: pd.DataFrame, col: str) -> dict:
    loc = frame.index.tz_convert("Europe/Madrid")
    night = loc.normalize() - pd.to_timedelta((loc.hour < 7).astype(int), unit="D")
    f = pd.DataFrame({"v": frame[col].values, "h": loc.hour, "n": night})
    out = {}
    for n, g in f.groupby("n"):
        by = g.groupby("h")["v"].mean()
        if set(WINDOW) <= set(by.index) and not by.loc[WINDOW].isna().any():
            out[n] = [float(by.get(x, by.mean())) for x in range(24)]
    return out


def main() -> None:
    k = pd.read_csv(HERE / "data/raw/energy_dataset.csv", parse_dates=["time"], index_col="time")
    k.index = pd.to_datetime(k.index, utc=True)
    k = k[~k.index.duplicated()]
    fr = pd.DataFrame({"ci": carbon_intensity(k), "px": k["price actual"]}).dropna()
    ci, px = curves(fr, "ci"), curves(fr, "px")
    both = sorted(set(ci) & set(px))

    print("== finding 2: whole record ==")
    arrive = sum(1 for n in ci if min(WINDOW, key=lambda h: ci[n][h]) == 18) / len(ci) * 100
    print(f"nights {len(ci)} · cleanest hour of the window is 18:00 on {arrive:.0f}% of nights")
    sv = []
    for n in ci:
        a, b = emis(NAIVE, ci[n]), emis(fill(ci[n]), ci[n])
        sv.append((1 - b / a) * 100 if a else 0.0)
    print(f"mean {statistics.mean(sv):.1f}% · median {statistics.median(sv):.1f}% · <1% {sum(s < 1 for s in sv) / len(sv) * 100:.1f}% "
          f"· <5% {sum(s < 5 for s in sv) / len(sv) * 100:.1f}% · >20% {sum(s > 20 for s in sv) / len(sv) * 100:.1f}%")

    print("\n== finding 5: do the cheapest and the cleanest hour coincide? ==")
    same, cors = 0, []
    for n in both:
        cw, pw = [ci[n][h] for h in WINDOW], [px[n][h] for h in WINDOW]
        if WINDOW[int(np.argmin(cw))] == WINDOW[int(np.argmin(pw))]:
            same += 1
        if np.std(cw) > 0 and np.std(pw) > 0:
            cors.append(float(np.corrcoef(cw, pw)[0, 1]))
    print(f"coincide on {same / len(both) * 100:.1f}% of {len(both)} nights · mean within-night correlation {statistics.mean(cors):.2f}")

    print("\n== finding 7: where the arrival hour sits against the night's mean ==")
    arr = [(c[18] / (sum(c[h] for h in WINDOW) / len(WINDOW)) - 1) * 100 for c in ci.values()]
    print(f"Spain: arrival hour is {statistics.mean(arr):+.1f}% against the window mean")
    rg = json.loads((HERE.parent / "frontend/src/data/regions.json").read_text(encoding="utf-8"))
    for g in rg["regions"]:
        print(f"{g['name']}: shape pos 0 rel {g['shape'][0]['rel']:+.1f}%, mean intensity {g['mean']}, median spread {g['median_window_spread_pct']}%")

    print("\n== finding 6: forecast vs perfect foresight on the served nights ==")
    days = json.loads((HERE.parent / "backend/app/data/grid_days.json").read_text(encoding="utf-8"))["days"]
    rows = []
    for d, p in days.items():
        c, f = p["carbon"], p["carbon_forecast"]
        en = emis(NAIVE, c)
        rows.append((d, (1 - emis(fill(c), c) / en) * 100, (1 - emis(fill(f), c) / en) * 100))
    for d, perfect, fc in sorted(rows, key=lambda r: -r[1])[:3] + sorted(rows, key=lambda r: r[2])[:3]:
        print(f"{d}  perfect {perfect:5.1f}%  on forecast {fc:5.1f}%")
    print(f"nights where the forecast schedule is worse than charging on arrival: {sum(1 for r in rows if r[2] < -1e-9)} of {len(rows)}")


if __name__ == "__main__":
    main()
