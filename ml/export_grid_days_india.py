"""Export Indian charging nights for the API (`era: "IN"`), built like the Spanish eras.

India becomes a first-class scenario in the simulator: measured carbon from Grid-India's 15-minute
Daily PSP reports (via `india_carbon.hourly`, IPCC AR5 factors, finding 12), an Indian residential
baseline, and rupee prices. Each stored night is 18:00 -> 07:00 stitched across two dates, with the
same 24-slot convention as `export_grid_days.py` (index 18-23 evening of day D, 0-7 morning of D+1,
8-17 midday of D).

What is measured and what is assumed:

  MEASURED   hourly carbon intensity for every night (Indian Standard Time).
  ASSUMED    the price curve. Most Indian households are on a flat domestic tariff; a few states
             run time-of-day structures. The curve here is ILLUSTRATIVE: a flat energy charge with
             a night rebate in 00:00-06:00, the shape CEEW describes for Maharashtra's FY26 order
             (rebate INR 0.80 per unit; sources disagree on the exact hours). It is there so the
             cost objective has something to respond to, not as a quoted tariff. Levels are not
             sourced. See `price_note`.
  PREDICTED  the residential baseline: a real Spanish household shape (GoiEner, 2018) rescaled to
             Pune's published 225 W evening peak (`validation/india.py`), because no open Indian
             household data exists. See the Validation pane.

No forecaster is trained for Indian carbon, so nights carry no `carbon_forecast`: finding 15 showed
no forecaster beats charging on arrival overnight in India, and the API falls back to perfect
foresight.

    python export_grid_days_india.py
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

from india_carbon import hourly  # noqa: E402
from spread_gate import NAIVE, emis, fill  # noqa: E402

OUT = HERE.parent / "backend" / "app" / "data" / "grid_days_in.json"
VAL = HERE / "artifacts" / "validation_india.json"
STRIDE = 8
BASE_INR_PER_KWH = 7.0          # ASSUMED flat domestic energy charge, rupees per kWh
NIGHT_REBATE_INR = 0.80         # ILLUSTRATIVE: CEEW's description of the MERC FY26 rebate
REBATE_HOURS = range(0, 6)      # 00:00-06:00


def price_curve() -> list[float]:
    return [round(BASE_INR_PER_KWH - (NIGHT_REBATE_INR if h in REBATE_HOURS else 0.0), 3) for h in range(24)]


def main() -> None:
    h = hourly()
    h["ts"] = pd.to_datetime(h["timestamp"])
    s = h.set_index("ts")["ci"]
    days = sorted({t.date() for t in s.index})
    curves: dict[str, list[float]] = {}
    for d in days:
        nxt = d + pd.Timedelta(days=1)
        slot: dict[int, float] = {}
        for hr in list(range(8, 24)):
            t = pd.Timestamp(d) + pd.Timedelta(hours=hr)
            if t in s.index:
                slot[hr] = float(s.loc[t])
        for hr in range(0, 8):
            t = pd.Timestamp(nxt) + pd.Timedelta(hours=hr)
            if t in s.index:
                slot[hr] = float(s.loc[t])
        if all(x in slot for x in list(range(18, 24)) + list(range(0, 8))):
            fillv = float(np.mean([slot[x] for x in list(range(18, 24)) + list(range(0, 8))]))
            curves[str(d)] = [round(slot.get(x, fillv), 1) for x in range(24)]

    cuts = {}
    tot_n = tot_o = 0.0
    for k, c in curves.items():
        en, eo = emis(NAIVE, c), emis(fill(c), c)
        cuts[k] = (1 - eo / en) * 100 if en else 0.0
        tot_n += en
        tot_o += eo
    ser = pd.Series(cuts)
    year_stats = {
        "year": "2025-26", "nights": int(len(ser)), "median_saving_pct": round(float(ser.median()), 1),
        "total_saving_pct": round((1 - tot_o / tot_n) * 100, 1),
        "under_1pct": int(round((ser < 1).mean() * 100)), "over_20pct": int(round((ser > 20).mean() * 100)),
    }
    keys = sorted(curves)
    keep = set(keys[::STRIDE])
    gap = ser.sub(ser.median()).abs()
    ties = sorted(gap[gap == gap.min()].index)          # many nights tie at the median (0.0%)
    default = ties[len(ties) // 2]                         # take the middle date, not the first
    keep.add(default)
    val = json.loads(VAL.read_text(encoding="utf-8"))
    synth = next(x for x in val["synthetic"] if x["shape_source"] == "spain" and x["scaling"].startswith("Pune"))
    per_home = [round(v / val["homes"], 4) for v in synth["profile_kw"]]
    prices = price_curve()
    out = {
        "description": "Indian charging nights, 18:00 to 07:00 IST, from Grid-India Daily PSP reports.",
        "region": "IN", "era": "IN", "timezone": "Asia/Kolkata", "currency": "INR",
        "units": {"carbon": "gCO2eq/kWh", "price": "INR/kWh"},
        "source": "Grid-India Daily PSP reports (15-minute, derived to hourly), IPCC AR5 lifecycle factors",
        "carbon_derivation": "fuel mix weighted by IPCC AR5 factors; the sheet's single THERMAL column is treated as coal",
        "default_day": str(default),
        "default_day_note": "the median-saving night of the period",
        "year_stats": year_stats,
        "price_includes_fixed": True,
        "price_note": "ILLUSTRATIVE: flat INR 7.00/kWh with a INR 0.80 rebate 00:00-06:00, after the shape CEEW "
                      "describes for Maharashtra FY26. Levels are assumptions, not a quoted tariff.",
        "residential_baseline_kw_per_home": per_home,
        "residential_baseline_note": "PREDICTED: a real Spanish household shape (GoiEner) rescaled to Pune's "
                                     "published 225 W evening peak. No open Indian household data exists.",
        "days": {k: {"carbon": curves[k], "price": prices} for k in sorted(keep)},
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"{len(out['days'])} nights of {len(curves)} · default {default} · year stats {year_stats} · {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
