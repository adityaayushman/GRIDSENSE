"""Attach a day-ahead forecast to every night the API serves.

The dashboard has been scheduling against *measured* carbon intensity, which is
perfect foresight — information no real scheduler has the evening before. This
computes what the deployed ridge model would have predicted for each stored
night and writes it alongside the measured curve, so the API can schedule on the
forecast and still score the result against what actually happened.

The features (lags, day-ahead TSO forecasts, rolling statistics) only exist in
the training frame, so the prediction is precomputed here rather than at request
time. Serving stays a lookup: no scikit-learn in the function bundle.

    python export_forecast_curves.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "src"))
sys.path.insert(0, str(HERE.parent / "backend"))

from train_v2 import build  # noqa: E402

MODEL = HERE / "artifacts" / "ridge_forecaster.json"
GRID_DAYS = HERE.parent / "backend" / "app" / "data" / "grid_days.json"

ARRIVAL, DEADLINE = 18, 7


def main() -> None:
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    coefs = np.array(model["coefficients"])
    feats = model["features"]

    data, built_feats = build(with_weather=False)
    assert built_feats == feats, (
        "feature set drifted from the exported model — retrain and re-export "
        "before attaching forecasts, or the coefficients apply to the wrong columns"
    )

    pred = data[feats].to_numpy() @ coefs + model["intercept"]
    frame = pd.DataFrame({"pred": pred}, index=data.index)
    local = frame.index.tz_convert("Europe/Madrid")
    frame["date"] = local.date
    frame["hour"] = local.hour
    by_day = frame.groupby(["date", "hour"])["pred"].mean().unstack()

    bundle = json.loads(GRID_DAYS.read_text(encoding="utf-8"))
    days = bundle["days"]

    attached, skipped = 0, []
    for key, payload in days.items():
        d = pd.Timestamp(key).date()
        nxt = (pd.Timestamp(key) + pd.Timedelta(days=1)).date()
        if d not in by_day.index or nxt not in by_day.index:
            skipped.append(key)
            continue
        # Stitch exactly as the measured curve is stitched: evening from day D,
        # early hours from D+1. A mismatch here would silently compare a
        # forecast for one night against actuals from another.
        try:
            curve = [
                float(by_day.loc[nxt if h < DEADLINE else d, h]) for h in range(24)
            ]
        except KeyError:
            skipped.append(key)
            continue
        if any(np.isnan(c) for c in curve):
            skipped.append(key)
            continue
        payload["carbon_forecast"] = [round(c, 1) for c in curve]
        attached += 1

    bundle["forecast"] = {
        "model": model["model"],
        "test_mae": model["test_mae"],
        "captured_pct": model["captured_pct"],
        "nights_with_forecast": attached,
        "note": "Day-ahead ridge prediction, precomputed. Scheduling on this and "
                "scoring against `carbon` is the honest measurement; scheduling on "
                "`carbon` directly is perfect foresight.",
    }
    GRID_DAYS.write_text(json.dumps(bundle, separators=(",", ":")), encoding="utf-8")

    errs = [
        abs(a - b)
        for p in days.values() if "carbon_forecast" in p
        for a, b in zip(p["carbon"], p["carbon_forecast"])
    ]
    print(f"nights with a forecast : {attached}/{len(days)}")
    if skipped:
        print(f"skipped (no features)  : {len(skipped)} -> {skipped[:4]}")
    print(f"mean abs error on served nights: {np.mean(errs):.2f} gCO2eq/kWh")
    print(f"wrote {GRID_DAYS} ({GRID_DAYS.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
