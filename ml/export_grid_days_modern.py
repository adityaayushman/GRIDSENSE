"""Export 2025 charging nights for the API: measured carbon and price, and a day-ahead forecast.

The API has served 2018 nights since the beginning. This adds the grid as it is now
(`era: "2025"`), built the same way as `export_grid_days.py`:

  * one 24-slot curve per charging night, 18:00 -> 07:00 stitched across two calendar
    dates (index 18-23 evening of day D, 0-7 the morning of D+1, 8-17 midday of D);
  * measured carbon intensity from the generation mix with IPCC AR5 factors;
  * the day-ahead market price, EUR/kWh;
  * a precomputed day-ahead forecast from `ridge_forecaster_modern.json`, trained on
    2022-2024 so that no served night was seen in training.

Every eighth night, for the same reason as the 2018 file (a small bundle that still
spans every season), and the default night is the median-saving one so the demo is
representative rather than cherry-picked. Whole-year statistics are computed over
*all* nights, not the sample, and stored for the UI to quote.

    python export_grid_days_modern.py
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

from spread_gate import NAIVE, emis, fill  # noqa: E402
from train_modern import features, load  # noqa: E402

MODEL = HERE / "artifacts" / "ridge_forecaster_modern.json"
OUT = HERE.parent / "backend" / "app" / "data" / "grid_days_2025.json"
YEAR = 2025
ARRIVAL, DEADLINE = 18, 7
STRIDE = 8


def main() -> None:
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    d = load()
    f = features(d)
    assert model["features"] == [c for c in model["features"] if c in f.columns], "feature drift"
    pred = pd.Series(f[model["features"]].to_numpy() @ np.array(model["coefficients"]) + model["intercept"], index=f.index)

    local = f.index.tz_convert("Europe/Madrid")
    frame = pd.DataFrame({
        "ci": f["ci"].values, "px": (d["price_eur_mwh"].reindex(f.index).values / 1000.0), "fc": pred.values,
        "date": local.date, "hour": local.hour,
    }, index=f.index)
    by = {k: frame.groupby(["date", "hour"])[k].mean().unstack() for k in ("ci", "px", "fc")}

    days_all, curves = [], {}
    dates = sorted(set(by["ci"].index))
    for day in dates:
        if day.year != YEAR:
            continue
        nxt = day + pd.Timedelta(days=1)
        if nxt not in by["ci"].index:
            continue
        try:
            def stitch(tab):
                return [float(tab.loc[nxt if h < DEADLINE else day, h]) for h in range(24)]
            c, p, g = stitch(by["ci"]), stitch(by["px"]), stitch(by["fc"])
        except KeyError:
            continue
        if any(np.isnan(x) for x in c + p + g):
            continue
        curves[str(day)] = {"carbon": [round(x, 1) for x in c], "price": [round(x, 5) for x in p],
                            "carbon_forecast": [round(x, 1) for x in g]}
        days_all.append(str(day))

    # Whole-year statistics over every night, on perfect foresight, as in finding 2.
    savings, e_naive_tot, e_opt_tot = [], 0.0, 0.0
    for k in days_all:
        c = curves[k]["carbon"]
        en, eo = emis(NAIVE, c), emis(fill(c), c)
        savings.append((1 - eo / en) * 100 if en else 0.0)
        e_naive_tot += en
        e_opt_tot += eo
    year_stats = {
        "year": YEAR, "nights": len(days_all),
        "median_saving_pct": round(statistics.median(savings), 1),
        "total_saving_pct": round((1 - e_opt_tot / e_naive_tot) * 100, 1),
        "under_1pct": round(sum(1 for s in savings if s < 1) / len(savings) * 100),
        "over_20pct": round(sum(1 for s in savings if s > 20) / len(savings) * 100),
    }

    served = days_all[::STRIDE]
    sv = {k: (1 - emis(fill(curves[k]["carbon"]), curves[k]["carbon"]) / emis(NAIVE, curves[k]["carbon"])) * 100 for k in served}
    default_day = sorted(served, key=lambda k: sv[k])[len(served) // 2]

    out = {
        "description": "Measured hourly grid carbon intensity and day-ahead price for Spain in 2025, stitched into "
                       "18:00-07:00 charging nights. Index 0-7 is the morning of the following day.",
        "region": "ES", "era": str(YEAR), "timezone": "Europe/Madrid",
        "units": {"carbon": "gCO2eq/kWh", "price": "EUR/kWh"},
        "source": "Energy-Charts (Fraunhofer ISE, CC BY 4.0): generation and day-ahead price republished from ENTSO-E",
        "carbon_derivation": "generation mix weighted by IPCC AR5 lifecycle emission factors (see ml/fetch_spain_ec.py)",
        "default_day": default_day,
        "default_day_note": "median emissions saving across the exported nights, chosen so the demo is representative not cherry-picked",
        "year_stats": year_stats,
        "days": {k: curves[k] for k in served},
        "forecast": {
            "model": model["model"], "test_mae": model["test_mae"], "captured_pct": model["captured_pct"],
            "trained_on": model["trained_on"], "nights_with_forecast": len(served),
            "note": "Day-ahead ridge prediction using the TSO's day-ahead solar, wind and load forecasts, precomputed. "
                    "Trained on 2022-2024 and never shown 2025. Scheduling on this and scoring against `carbon` is the "
                    "honest measurement; scheduling on `carbon` directly is perfect foresight.",
        },
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"{len(served)} served nights of {len(days_all)} in {YEAR}; default {default_day}")
    print(f"whole-year (perfect foresight): median saving {year_stats['median_saving_pct']}%, total {year_stats['total_saving_pct']}%, "
          f"{year_stats['under_1pct']}% of nights under 1%, {year_stats['over_20pct']}% over 20%")
    print(f"forecast: MAE {model['test_mae']}, captures {model['captured_pct']}%")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
