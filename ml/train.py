"""Train a day-ahead carbon-intensity forecaster and evaluate it by decision regret.

Setup
-----
A forecast is issued at 23:00 on day D covering all 24 hours of day D+1. Only
information available at that moment is used:

  * TSO day-ahead forecasts of solar, wind and load (published before the day
    starts, so legitimately available)
  * calendar features
  * lags of carbon intensity at >= 24h, so nothing from the target day leaks in

Split is temporal: 2015-2017 trains, 2018 tests. No shuffling — shuffling a time
series lets the model interpolate between neighbouring hours it will not have at
serving time, which inflates scores.

Evaluation
----------
MAE/RMSE are reported, but the metric that decides whether this forecaster is
worth anything is *decision regret*: schedule the fleet using the forecast, then
score that schedule against actual carbon intensity, and compare to a
perfect-foresight schedule. A forecast with mediocre MAE can still be worth
~100% of the achievable saving if it ranks hours correctly, since the optimizer
only cares about which hours are cleanest.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error

sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.optimizer import Vehicle, naive_schedule, optimize_schedule  # noqa: E402
from carbon import carbon_intensity  # noqa: E402

RAW = Path(__file__).parent / "data" / "raw" / "energy_dataset.csv"
ARTIFACTS = Path(__file__).parent / "artifacts"
TRAIN_END = "2017-12-31 23:00:00+00:00"

ARRIVAL, DEADLINE = 18, 7
EV_COUNT, ENERGY_KWH, CHARGER_KW = 80, 9.2, 7.0

DAY_AHEAD_COLS = [
    "forecast solar day ahead",
    "forecast wind onshore day ahead",
    "total load forecast",
]


def build_frame() -> pd.DataFrame:
    df = pd.read_csv(RAW, parse_dates=["time"], index_col="time")
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[~df.index.duplicated(keep="first")].sort_index()
    # Reindex onto a strict hourly grid so lag arithmetic is positional-safe.
    df = df.reindex(pd.date_range(df.index.min(), df.index.max(), freq="h", tz="UTC"))

    out = pd.DataFrame(index=df.index)
    out["ci"] = carbon_intensity(df)
    for c in DAY_AHEAD_COLS:
        out[c] = df[c]

    # Short gaps only; anything longer stays NaN and is dropped.
    out = out.interpolate(limit=3, limit_direction="both")

    idx = out.index
    out["hour"] = idx.hour
    out["dow"] = idx.dayofweek
    out["month"] = idx.month
    out["is_weekend"] = (idx.dayofweek >= 5).astype(int)
    # Cyclical encodings so hour 23 and hour 0 are adjacent for the linear model.
    out["hour_sin"] = np.sin(2 * np.pi * idx.hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * idx.hour / 24)
    out["doy_sin"] = np.sin(2 * np.pi * idx.dayofyear / 365.25)
    out["doy_cos"] = np.cos(2 * np.pi * idx.dayofyear / 365.25)

    # Lags >= 24h only: the forecast is issued at 23:00 the previous day.
    for lag in (24, 25, 48, 168):
        out[f"ci_lag_{lag}"] = out["ci"].shift(lag)
    out["ci_lag24_daymean"] = out["ci"].shift(24).rolling(24).mean()
    out["ci_lag168_daymean"] = out["ci"].shift(168).rolling(24).mean()

    return out.dropna()


FEATURES = [
    *DAY_AHEAD_COLS,
    "hour", "dow", "month", "is_weekend",
    "hour_sin", "hour_cos", "doy_sin", "doy_cos",
    "ci_lag_24", "ci_lag_25", "ci_lag_48", "ci_lag_168",
    "ci_lag24_daymean", "ci_lag168_daymean",
]


def scores(name: str, y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    mae = mean_absolute_error(y_true, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    print(f"  {name:<28} MAE {mae:7.2f}   RMSE {rmse:7.2f}")
    return {"model": name, "mae": round(mae, 3), "rmse": round(rmse, 3)}


def decision_regret(test: pd.DataFrame, pred: pd.Series, label: str) -> dict:
    """Schedule on the forecast, score on actuals, compare to perfect foresight."""
    fleet = [Vehicle("agg", ENERGY_KWH * EV_COUNT, CHARGER_KW * EV_COUNT, ARRIVAL, DEADLINE)]
    naive = naive_schedule(fleet)

    local = test.index.tz_convert("Europe/Madrid")
    hours = local.hour
    night = local.normalize() - pd.to_timedelta((hours < DEADLINE).astype(int), unit="D")
    window = [h % 24 for h in range(ARRIVAL, ARRIVAL + (24 - ARRIVAL + DEADLINE))]

    frame = pd.DataFrame(
        {"actual": test["ci"].values, "pred": pred.values, "hour": hours, "night": night}
    )

    e_naive = e_fc = e_oracle = 0.0
    nights = 0
    for _, grp in frame.groupby("night"):
        a = grp.groupby("hour")["actual"].mean()
        p = grp.groupby("hour")["pred"].mean()
        if not set(window).issubset(a.index) or not set(window).issubset(p.index):
            continue
        actual = [float(a.get(h, a.mean())) for h in range(24)]
        forecast = [float(p.get(h, p.mean())) for h in range(24)]

        sched_fc = optimize_schedule(fleet, forecast, objective="emissions")
        sched_or = optimize_schedule(fleet, actual, objective="emissions")

        e_naive += sum(naive[h] * actual[h] for h in range(24)) / 1000
        e_fc += sum(sched_fc[h] * actual[h] for h in range(24)) / 1000
        e_oracle += sum(sched_or[h] * actual[h] for h in range(24)) / 1000
        nights += 1

    achievable = e_naive - e_oracle
    captured = e_naive - e_fc
    pct = captured / achievable * 100 if achievable > 0 else float("nan")
    print(f"  {label:<28} captures {pct:6.1f}% of achievable saving "
          f"({captured:,.0f} of {achievable:,.0f} kg over {nights} nights)")
    return {"model": label, "captured_pct": round(pct, 2),
            "captured_kg": round(captured, 1), "achievable_kg": round(achievable, 1)}


def main() -> None:
    ARTIFACTS.mkdir(exist_ok=True)
    data = build_frame()
    train = data.loc[:TRAIN_END]
    test = data.loc[TRAIN_END:].iloc[1:]
    print(f"train {train.index.min().date()} -> {train.index.max().date()}  ({len(train):,} rows)")
    print(f"test  {test.index.min().date()} -> {test.index.max().date()}  ({len(test):,} rows)\n")

    X_tr, y_tr = train[FEATURES], train["ci"]
    X_te, y_te = test[FEATURES], test["ci"]

    print("=== accuracy on held-out 2018 ===")
    report = []

    # Baseline 1: persistence — same hour yesterday.
    report.append(scores("persistence (lag 24h)", y_te, X_te["ci_lag_24"]))

    # Baseline 2: climatology from the training years only.
    clim = train.groupby(["month", "hour"])["ci"].mean()
    clim_pred = pd.MultiIndex.from_arrays([X_te["month"], X_te["hour"]]).map(clim)
    report.append(scores("climatology (month x hour)", y_te, clim_pred.to_numpy()))

    # Baseline 3: the curve the demo currently ships.
    import math
    synth = np.array([
        320 + 180 * math.exp(-((h - 19) ** 2) / 6) - 90 * math.exp(-((h - 13) ** 2) / 10)
        for h in range(24)
    ])
    report.append(scores("shipped synthetic curve", y_te, synth[X_te["hour"].to_numpy()]))

    ridge = Ridge(alpha=1.0).fit(X_tr, y_tr)
    p_ridge = ridge.predict(X_te)
    report.append(scores("ridge", y_te, p_ridge))

    gbm = HistGradientBoostingRegressor(
        max_iter=400, learning_rate=0.06, max_depth=6, random_state=0
    ).fit(X_tr, y_tr)
    p_gbm = gbm.predict(X_te)
    report.append(scores("gradient boosting", y_te, p_gbm))

    print("\n=== decision regret: does the forecast pick the right hours? ===")
    regret = [
        decision_regret(test, pd.Series(synth[X_te["hour"].to_numpy()], index=test.index),
                        "shipped synthetic curve"),
        decision_regret(test, pd.Series(clim_pred.to_numpy(), index=test.index),
                        "climatology"),
        decision_regret(test, X_te["ci_lag_24"], "persistence"),
        decision_regret(test, pd.Series(p_ridge, index=test.index), "ridge"),
        decision_regret(test, pd.Series(p_gbm, index=test.index), "gradient boosting"),
    ]

    # Deployable artifact: an empirical profile the API can read with no ML deps.
    profile = (
        data.groupby([data["month"], data["hour"]])["ci"].mean().round(1).unstack().values.tolist()
    )
    (ARTIFACTS / "carbon_profile.json").write_text(json.dumps(
        {
            "description": "Mean grid carbon intensity (gCO2eq/kWh) by [month-1][hour], "
                           "derived from ENTSO-E Spain 2015-2018 generation mix.",
            "source": "kaggle: nicholasjhana/energy-consumption-generation-prices-and-weather",
            "units": "gCO2eq/kWh",
            "profile": profile,
        },
        indent=2,
    ))

    # Ridge exports as plain coefficients, so the API can score a forecast with
    # a dot product and no scikit-learn dependency in the serverless bundle.
    ridge_artifact = {
        "description": "Day-ahead carbon-intensity forecaster. "
                       "prediction = intercept + sum(coef[i] * feature[i])",
        "units": "gCO2eq/kWh",
        "features": FEATURES,
        "coefficients": [float(c) for c in ridge.coef_],
        "intercept": float(ridge.intercept_),
        "trained_on": f"{train.index.min().date()}..{train.index.max().date()}",
        "test_mae": round(float(mean_absolute_error(y_te, p_ridge)), 3),
    }
    (ARTIFACTS / "ridge_forecaster.json").write_text(json.dumps(ridge_artifact, indent=2))

    # Round-trip check: the exported coefficients must reproduce sklearn exactly.
    manual = X_te.to_numpy() @ np.array(ridge_artifact["coefficients"]) + ridge_artifact["intercept"]
    drift = float(np.abs(manual - p_ridge).max())
    assert drift < 1e-6, f"exported ridge diverges from sklearn by {drift}"
    print(f"\nridge export round-trip OK (max drift {drift:.2e})")

    # Real measured daily curves — lets the demo show actual grid days instead
    # of a fabricated curve, with no model or API key needed at serve time.
    local = data.index.tz_convert("Europe/Madrid")
    daily = (
        pd.DataFrame({"ci": data["ci"].values, "date": local.date, "hour": local.hour})
        .groupby(["date", "hour"])["ci"].mean().unstack()
    )
    daily = daily.dropna(axis=0)
    daily = daily[sorted(daily.columns)]
    curves = {str(d): [round(float(v), 1) for v in row] for d, row in daily.iterrows()}
    curves = {d: c for d, c in curves.items() if len(c) == 24 and d.startswith("2018")}
    (ARTIFACTS / "real_daily_curves.json").write_text(json.dumps(
        {
            "description": "Measured hourly grid carbon intensity by local date, "
                           "derived from ENTSO-E Spain generation mix.",
            "units": "gCO2eq/kWh",
            "timezone": "Europe/Madrid",
            "source": "kaggle: nicholasjhana/energy-consumption-generation-prices-and-weather",
            "curves": curves,
        },
        indent=2,
    ))

    (ARTIFACTS / "metrics.json").write_text(json.dumps(
        {"accuracy": report, "decision_regret": regret}, indent=2
    ))
    print(f"wrote {ARTIFACTS / 'carbon_profile.json'}")
    print(f"wrote {ARTIFACTS / 'ridge_forecaster.json'}")
    print(f"wrote {ARTIFACTS / 'real_daily_curves.json'} ({len(curves)} days)")
    print(f"wrote {ARTIFACTS / 'metrics.json'}")


if __name__ == "__main__":
    main()
