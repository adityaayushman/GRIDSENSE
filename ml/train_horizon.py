"""A forecaster whose error depends on how far ahead you are asking.

The existing day-ahead model (train_v2.py) makes one prediction per hour and
never revises it. That is the right model for a scheduler that decides the whole
night at 18:00, but it cannot justify a rolling-horizon controller: re-solving
at 02:00 against a forecast made at 18:00 uses no new information, so the plan
does not change and the "controller" is decoration.

A rolling controller is only worth building if forecasts improve as the target
approaches. That is an empirical claim about this data, so this trains one ridge
per horizon h = 1..13 and reports MAE(h). Each model sees:

  * carbon intensity actually *observed* up to the decision hour (lags 0, 1, 2,
    and 24) — the information a controller gains by waiting,
  * the day-ahead solar / wind / load forecasts for the target hour — known at
    18:00 and unchanged since, so this is what the one-shot model already had,
  * calendar features for the target hour.

If MAE(h) is flat, the honest conclusion is that MPC buys nothing here and the
one-shot LP is the right design. Written to be capable of returning that answer.

    python train_horizon.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "src"))

from carbon import carbon_intensity  # noqa: E402

RAW = HERE / "data" / "raw" / "energy_dataset.csv"
OUT = HERE / "artifacts" / "horizon_forecaster.json"

#: 18:00 -> 07:00 is thirteen hours, so a decision at 18:00 looks 13 ahead.
MAX_HORIZON = 13
TRAIN_END = "2017-12-31"

EXOG = [
    "forecast solar day ahead",
    "forecast wind onshore day ahead",
    "total load forecast",
]


def load_frame() -> pd.DataFrame:
    e = pd.read_csv(RAW, parse_dates=["time"], index_col="time")
    e.index = pd.to_datetime(e.index, utc=True)
    e = e[~e.index.duplicated()].sort_index()

    ci = carbon_intensity(e).dropna()
    df = pd.DataFrame({"ci": ci})
    for c in EXOG:
        df[c] = e[c].reindex(df.index).interpolate(limit=3)
    return df.dropna()


def build(df: pd.DataFrame, h: int) -> tuple[pd.DataFrame, pd.Series]:
    """Features known at hour t for predicting carbon intensity at t + h."""
    x = pd.DataFrame(index=df.index)

    # Observed history — the only thing that improves as the decision hour moves.
    x["lag0"] = df["ci"]
    x["lag1"] = df["ci"].shift(1)
    x["lag2"] = df["ci"].shift(2)
    x["lag24"] = df["ci"].shift(24)
    # Recent trend: a grid mid-ramp keeps ramping for an hour or two.
    x["delta"] = df["ci"] - df["ci"].shift(1)
    x["roll6"] = df["ci"].rolling(6).mean()

    # Day-ahead exogenous forecasts, read at the *target* hour. Published once
    # the previous day, so a controller gains nothing by waiting for these.
    for c in EXOG:
        x[f"exog_{c}"] = df[c].shift(-h)

    # Calendar of the target hour.
    tgt_hour = (df.index.hour + h) % 24
    x["tgt_sin"] = np.sin(2 * np.pi * tgt_hour / 24)
    x["tgt_cos"] = np.cos(2 * np.pi * tgt_hour / 24)
    x["dow"] = df.index.dayofweek

    y = df["ci"].shift(-h)
    ok = x.notna().all(axis=1) & y.notna()
    return x[ok], y[ok]


def main() -> None:
    df = load_frame()
    print(f"{len(df):,} hours, {df.index.min().date()} -> {df.index.max().date()}\n")

    models, rows = {}, []
    persistence_ref = None

    for h in range(1, MAX_HORIZON + 1):
        x, y = build(df, h)
        tr = x.index <= pd.Timestamp(TRAIN_END, tz="UTC")
        xtr, ytr, xte, yte = x[tr], y[tr], x[~tr], y[~tr]

        m = Ridge(alpha=1.0).fit(xtr, ytr)
        mae = mean_absolute_error(yte, m.predict(xte))

        # Baseline: assume nothing changes. Beating this is the minimum bar.
        naive_mae = mean_absolute_error(yte, xte["lag0"])
        if h == 1:
            persistence_ref = naive_mae

        models[str(h)] = {
            "coefficients": [float(c) for c in m.coef_],
            "intercept": float(m.intercept_),
            "test_mae": round(float(mae), 3),
            "persistence_mae": round(float(naive_mae), 3),
        }
        rows.append((h, mae, naive_mae, len(xte)))

    print(f"{'horizon':>7} {'ridge MAE':>10} {'persistence':>12} {'skill':>7}")
    for h, mae, nm, n in rows:
        print(f"{h:>7} {mae:>10.2f} {nm:>12.2f} {(1 - mae / nm) * 100:>6.1f}%")

    near = np.mean([r[1] for r in rows if r[0] <= 3])
    far = np.mean([r[1] for r in rows if r[0] >= 10])
    print(f"\n  1-3h ahead   MAE {near:.2f}")
    print(f"  10-13h ahead MAE {far:.2f}")
    print(f"  degradation  {far / near:.2f}x")

    if far / near < 1.15:
        print("\n  Forecast quality barely decays with horizon. A rolling controller")
        print("  would re-solve against essentially the same information each hour,")
        print("  so MPC cannot beat the one-shot LP by much. Reconsider the design.")
    else:
        print(f"\n  Forecasts {far / near:.2f}x worse at the far end of the window. A")
        print("  controller that waits and re-solves has materially better information")
        print("  for the hours it is about to commit. MPC has something to exploit.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "description": "Per-horizon carbon-intensity forecasters for the MPC scheduler. "
                       "prediction = intercept + sum(coef[i] * feature[i])",
        "units": "gCO2eq/kWh",
        "model": "ridge(alpha=1.0), one per horizon",
        "features": list(build(df, 1)[0].columns),
        "trained_on": f"..{TRAIN_END}",
        "tested_on": f"{TRAIN_END}..{df.index.max().date()}",
        "max_horizon": MAX_HORIZON,
        "horizons": models,
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
