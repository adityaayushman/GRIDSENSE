"""India's five regional grids, from the same Daily PSP reports (section A of the MOP_E sheet).

The national series hides a lot. The reports also give, per region (NR, WR, SR, ER, NER), the day's energy
met, the hydro, wind and solar energy generated inside the region, and the demand met at the evening peak
and at the day's maximum, with its time. That is daily, not hourly, and the reports carry no fuel mix per
region, so this cannot give a regional carbon-intensity curve. What it can give:

  * how clean each region's own supply is, as (hydro + wind + solar) / energy met
  * WHEN each region peaks. An evening-peaking region is one where EVs arriving at 18:00 land on the peak;
    a midday-peaking region has a clean-solar afternoon and an evening that is already off-peak.

Regional energy met includes imports from other regions, so the renewable share is the share of what the
region consumes that it generated itself from those three sources. It undercounts nuclear and any
renewable the sheet does not break out, and says nothing about the thermal fuel.

    python india_regions.py      # -> artifacts/india_regions.json, frontend/src/data/india_regions.json
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
RAW = HERE / "data" / "india-psp" / "raw"
OUTS = [HERE / "artifacts" / "india_regions.json", HERE.parent / "backend" / "app" / "data" / "india_regions.json",
        HERE.parent / "frontend" / "src" / "data" / "india_regions.json"]
REGIONS = ["NR", "WR", "SR", "ER", "NER"]
NAMES = {"NR": "Northern", "WR": "Western", "SR": "Southern", "ER": "Eastern", "NER": "North-Eastern"}

ROWS = {
    "evening_peak_mw": re.compile(r"^demand met.*evening", re.I),
    "energy_mu": re.compile(r"^energy met", re.I),
    "hydro_mu": re.compile(r"^hydro gen", re.I),
    "wind_mu": re.compile(r"^wind gen", re.I),
    "solar_mu": re.compile(r"^solar gen", re.I),
    "max_mw": re.compile(r"^maximum demand met", re.I),
    "max_time": re.compile(r"^time of maximum", re.I),
}


def num(v):
    try:
        x = float(str(v).replace(",", "").strip())
        return x
    except ValueError:
        return 0.0 if str(v).strip() in ("-", "") else None


def parse(path: Path) -> dict | None:
    try:
        d = pd.read_excel(path, sheet_name="MOP_E", header=None)
    except Exception:
        return None
    head = None
    for i in range(min(len(d), 20)):
        cells = [str(c).strip() for c in d.iloc[i].tolist()]
        if all(r in cells for r in REGIONS):
            head = {r: cells.index(r) for r in REGIONS}
            break
    if head is None:
        return None
    out: dict = {}
    for i in range(head_row(d, head) + 1, min(len(d), 40)):
        label = str(d.iloc[i, 0]).strip()
        for key, rx in ROWS.items():
            if key not in out and rx.search(label):
                out[key] = {r: d.iloc[i, c] for r, c in head.items()}
    if len(out) < len(ROWS):
        return None
    return out


def head_row(d: pd.DataFrame, head: dict) -> int:
    for i in range(min(len(d), 20)):
        cells = [str(c).strip() for c in d.iloc[i].tolist()]
        if all(r in cells for r in REGIONS):
            return i
    return 0


def hour_of(v) -> float | None:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", str(v))
    return int(m.group(1)) + int(m.group(2)) / 60 if m else None


def main() -> None:
    days = []
    for f in sorted(RAW.glob("*.xls")):
        p = parse(f)
        if p:
            days.append((f.stem, p))
    print(f"parsed {len(days)} of {len(list(RAW.glob('*.xls')))} reports")
    res = []
    for reg in REGIONS:
        shares, eve_ratio, peak_hours, month_share = [], [], [], {}
        for date, p in days:
            e = num(p["energy_mu"][reg])
            if not e or e <= 0:
                continue
            ren = sum(num(p[k][reg]) or 0.0 for k in ("hydro_mu", "wind_mu", "solar_mu"))
            sh = ren / e * 100
            if 0 <= sh <= 100:
                shares.append(sh)
                month_share.setdefault(date[:7], []).append(sh)
            mx, ev = num(p["max_mw"][reg]), num(p["evening_peak_mw"][reg])
            if mx and ev and mx > 0:
                eve_ratio.append(ev / mx * 100)
            h = hour_of(p["max_time"][reg])
            if h is not None:
                peak_hours.append(h)
        res.append({
            "key": reg, "name": NAMES[reg], "days": len(shares),
            "renewable_share_pct": round(statistics.mean(shares), 1),
            "renewable_share_p10_p90": [round(float(pd.Series(shares).quantile(0.1)), 1), round(float(pd.Series(shares).quantile(0.9)), 1)],
            "evening_peak_pct_of_max": round(statistics.median(eve_ratio), 1),
            "median_peak_hour": round(statistics.median(peak_hours), 1),
            "evening_peaking_days_pct": round(sum(1 for h in peak_hours if 18 <= h <= 23) / len(peak_hours) * 100),
            "midday_peaking_days_pct": round(sum(1 for h in peak_hours if 9 <= h < 17) / len(peak_hours) * 100),
            "monthly_share": {m: round(statistics.mean(v), 1) for m, v in sorted(month_share.items())},
        })
        r = res[-1]
        print(f"  {reg}: renewable {r['renewable_share_pct']}%  median peak {r['median_peak_hour']}h  evening-peaking {r['evening_peaking_days_pct']}% of days  evening/max {r['evening_peak_pct_of_max']}%")
    out = {"note": "Generated by ml/india_regions.py - daily regional figures from the Daily PSP reports, section A.",
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "span": f"{days[0][0]}..{days[-1][0]}", "days": len(days), "regions": res,
           "limits": "Daily resolution; no per-region fuel mix, so no regional carbon curve. Renewable share counts "
                     "hydro, wind and solar generated in the region over energy met (which includes imports)."}
    for p in OUTS:
        p.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {OUTS[0]}")


if __name__ == "__main__":
    main()
