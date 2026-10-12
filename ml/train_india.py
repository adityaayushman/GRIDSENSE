"""India forecasters on the merged master dataset: does weather and a longer record help?

Two questions, on the table `build_india_dataset.py` assembles:

  1. DEMAND (hourly national, 2019-2024, 46,728 hours). Does adding weather and
     calendar help over lags alone, and does a longer training history help?
     Demand is what sizes a transformer, and the project's hosting-capacity
     baseline takes its shape from it.
  2. CARBON (hourly intensity, 2025-04 onward, ~13,000 hours). Does weather
     (solar irradiance, cloud, wind) help a day-ahead carbon forecast, and what
     does the better forecast do to the gate (finding 13) on India?

Weather here is *observed* (ERA5 reanalysis), not a day-ahead forecast. That is
optimistic: a real system would use a numerical forecast, whose error would eat
part of the gain. Both variants are reported so the size of the weather effect
is visible, and the lag-only model is the conservative number.

Every lag is >= 24 h, so every feature is known at 23:00 the previous day.

    python train_india.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "src"))
sys.path.insert(0, str(HERE.parent / "backend"))

from spread_gate import evaluate, night_curves, sweep  # noqa: E402

MASTER = HERE / "data" / "india-big" / "india_master_hourly.csv"
OUT = HERE / "artifacts" / "india_models.json"

WEATHER = ["india_temp_c", "india_rh_pct", "india_cloud_pct", "india_ghi_wm2", "india_wind_kmh", "india_rain_mm",
           "jodhpur_ghi_wm2", "jodhpur_wind_kmh", "chennai_wind_kmh", "delhi_temp_c", "mumbai_temp_c", "chennai_temp_c"]
CALENDAR = ["hour", "dow", "month", "is_weekend", "is_holiday", "hour_sin", "hour_cos", "doy_sin", "doy_cos"]


def lag_block(s: pd.Series, name: str) -> pd.DataFrame:
    f = pd.DataFrame(index=s.index)
    for lag in (24, 25, 48, 72, 168):
        f[f"{name}_lag{lag}"] = s.shift(lag)
    d = s.shift(24)
    f[f"{name}_lag24_mean"], f[f"{name}_lag24_max"], f[f"{name}_lag24_min"] = (
        d.rolling(24).mean(), d.rolling(24).max(), d.rolling(24).min())
    f[f"{name}_trend"] = s.shift(24) - s.shift(168)
    return f


def mape(y: pd.Series, p: pd.Series) -> float:
    return float((np.abs(p - y) / y).mean() * 100)


def fit_eval(model, train, test, cols, target):
    model.fit(train[cols], train[target])
    pred = pd.Series(model.predict(test[cols]), index=test.index)
    return pred, float(np.abs(pred - test[target]).mean())


def gbm():
    return HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05, max_depth=8,
                                         min_samples_leaf=40, l2_regularization=1.0, random_state=0)


def demand_experiments(m: pd.DataFrame) -> dict:
    d = m[m["has_hourly_demand_kaggle"] == 1].copy()
    d = d[~d.index.duplicated()]
    y = d["demand_national_mw"].interpolate(limit=3)
    X = pd.concat([d[CALENDAR + [c for c in WEATHER if c in d.columns]], lag_block(y, "dem")], axis=1)
    X["y"] = y
    X = X.dropna()
    # Test: the final 12 months. Train: everything before, in growing windows.
    test_start = X.index.max() - pd.Timedelta(days=365)
    test = X[X.index > test_start]
    lag_cols = [c for c in X.columns if c.startswith("dem_")]
    cal_cols = lag_cols + CALENDAR
    all_cols = cal_cols + [c for c in WEATHER if c in X.columns]
    res: dict = {"test": f"{test.index.min():%Y-%m-%d}..{test.index.max():%Y-%m-%d}", "rows_test": len(test)}

    print(f"\nDEMAND  test {res['test']} ({len(test):,} h)")
    print(f"  {'features':<26} {'ridge MAE':>10} {'ridge MAPE':>11} {'gbm MAE':>9} {'gbm MAPE':>9}   (full history)")
    train_all = X[X.index <= test_start]
    feat_rows = {}
    for label, cols in (("lags only", lag_cols), ("lags + calendar", cal_cols), ("lags + calendar + weather", all_cols)):
        pr, mr = fit_eval(Ridge(alpha=1.0), train_all, test, cols, "y")
        pg, mg = fit_eval(gbm(), train_all, test, cols, "y")
        feat_rows[label] = {"ridge_mae": round(mr), "ridge_mape": round(mape(test["y"], pr), 2),
                            "gbm_mae": round(mg), "gbm_mape": round(mape(test["y"], pg), 2)}
        print(f"  {label:<26} {mr:>10,.0f} {feat_rows[label]['ridge_mape']:>10}% {mg:>9,.0f} {feat_rows[label]['gbm_mape']:>8}%")
    res["features"] = feat_rows

    print(f"\n  training volume (lags + calendar + weather, GBM):")
    vol = []
    for yrs in (1, 2, 3, 4):
        tr = train_all[train_all.index > test_start - pd.Timedelta(days=365 * yrs)]
        if len(tr) < 2000:
            continue
        pg, mg = fit_eval(gbm(), tr, test, all_cols, "y")
        vol.append({"train_years": yrs, "rows": len(tr), "mae": round(mg), "mape": round(mape(test["y"], pg), 2)})
        print(f"    last {yrs} yr  {len(tr):>7,} rows   MAE {mg:>8,.0f}   MAPE {vol[-1]['mape']}%")
    res["volume"] = vol
    return res


def carbon_experiments(m: pd.DataFrame) -> dict:
    p = m[m["has_psp_hourly"] == 1].copy()
    ci = p["ci_psp"].interpolate(limit=3)
    X = pd.concat([p[CALENDAR + [c for c in WEATHER if c in p.columns]], lag_block(ci, "ci"),
                   lag_block(p["psp_demand_met_mw"].interpolate(limit=3), "dem")], axis=1)
    X["y"] = ci
    X = X.dropna()
    cut = pd.Timestamp("2026-04-01")
    train, test = X[X.index < cut], X[X.index >= cut]
    lag_cols = [c for c in X.columns if c.startswith("ci_")]
    cal_cols = lag_cols + [c for c in X.columns if c.startswith("dem_")] + CALENDAR
    all_cols = cal_cols + [c for c in WEATHER if c in X.columns]
    print(f"\nCARBON  train {train.index.min():%Y-%m-%d}..{train.index.max():%Y-%m-%d} ({len(train):,} h)"
          f"  test {test.index.min():%Y-%m-%d}..{test.index.max():%Y-%m-%d} ({len(test):,} h)")
    res: dict = {"train_rows": len(train), "test_rows": len(test),
                 "test": f"{test.index.min():%Y-%m-%d}..{test.index.max():%Y-%m-%d}"}
    print(f"  {'model':<34} {'MAE':>7} {'captured':>9} {'gate@2% captured':>17} {'worse nights':>13}")
    rows = []
    for label, model, cols in (
        ("persistence (lag 24h)", None, None),
        ("ridge, lags only", Ridge(alpha=1.0), lag_cols),
        ("ridge, lags + calendar + demand", Ridge(alpha=1.0), cal_cols),
        ("ridge, + weather", Ridge(alpha=1.0), all_cols),
        ("gbm, lags + calendar + demand", gbm(), cal_cols),
        ("gbm, + weather", gbm(), all_cols),
    ):
        if model is None:
            pred, mae = test["ci_lag24"], float(np.abs(test["ci_lag24"] - test["y"]).mean())
        else:
            pred, mae = fit_eval(model, train, test, cols, "y")
        nights = night_curves(test["y"], pred, None)
        ev = evaluate(nights)
        ungated = sweep(ev, "pred_saving", [-1e9])[0]
        gated = sweep(ev, "pred_saving", [2.0])[0]
        rows.append({"model": label, "mae": round(mae, 2), "nights": len(ev),
                     "captured_pct": ungated["captured_of_oracle_pct"],
                     "worse_pct": ungated["worse_share_pct"],
                     "gated_2pct_total_saving": gated["total_saving_pct"],
                     "gated_2pct_worse_pct": gated["worse_share_pct"],
                     "ungated_total_saving": ungated["total_saving_pct"],
                     "oracle_total_saving": round(sum(r["e_naive"] - r["e_or"] for r in ev) / sum(r["e_naive"] for r in ev) * 100, 3)})
        r = rows[-1]
        print(f"  {label:<34} {mae:>7.1f} {str(r['captured_pct']) + '%':>9} {str(r['gated_2pct_total_saving']) + '%':>17} "
              f"{str(r['worse_pct']) + '%':>13}")
    res["models"] = rows
    print(f"  oracle (perfect foresight) overnight saving over the test span: {rows[0]['oracle_total_saving']}%")
    return res


def main() -> None:
    m = pd.read_csv(MASTER, index_col=0, parse_dates=True, low_memory=False)
    out = {"note": "Generated by ml/train_india.py", "demand": demand_experiments(m), "carbon": carbon_experiments(m)}
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
