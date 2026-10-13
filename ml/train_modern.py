"""A day-ahead carbon forecaster for the modern Spanish grid.

The deployed model was trained on 2015-2017 and is served on 2018 nights. Spain's
grid has since changed enormously (mean intensity 274 g/kWh in 2015, 132 in 2025;
solar roughly tripled), and finding 15 showed that what limits the forecaster is not
the volume of history but the TSO's day-ahead solar, wind and load forecasts. Those
are now in hand for 2015-2026 (`fetch_spain_forecasts_ec.py`), so this rebuilds the
model on the inputs that matter, trained on the grid as it is.

    python train_modern.py

Four things are measured, in this order:

  A. VALIDATION OF THE NEW SOURCE. The deployed split (train 2015-2017, test 2018) on
     the Energy-Charts record with the day-ahead features. If this does not land
     near the deployed Kaggle model (MAE 23.70, 71.0% captured), the new source or
     the feature build is wrong and nothing below can be trusted.
  B. WHAT THE FORECASTS ARE WORTH on the modern grid: with and without them.
  C. TRAINING WINDOW. How many recent years to use, chosen on 2024 and *not* on the
     test year, then scored on 2025.
  D. THE DEPLOYABLE MODEL: ridge (coefficients only, no scikit-learn at inference),
     trained on the chosen window ending 2024-12-31, scored on 2025, exported to
     artifacts/ridge_forecaster_modern.json. Serving 2025 nights from a model that
     never saw 2025 keeps the demo honest.

Scored by decision regret (the share of the achievable saving a forecast-driven
schedule captures, finding 3), not only by MAE.
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

EC = HERE / "data" / "es-ec"
OUT_JSON = HERE / "artifacts" / "modern_forecaster_metrics.json"
OUT_MODEL = HERE / "artifacts" / "ridge_forecaster_modern.json"
TEST_YEAR, VALID_YEAR = 2025, 2024
#: The forecast gate threshold (finding 13): the out-of-sample optimum on the corrected 2018 record,
#: and no loss of total saving on 2025.
GATE_TAU = 4.0
WINDOWS = (1, 2, 3, 5, 8)

TSO = ["fc_solar_mw", "fc_wind_mw", "fc_load_mw", "renew_share", "renew_share_lag24"]


def load() -> pd.DataFrame:
    gen = pd.read_csv(EC / "spain_hourly.csv", index_col=0, parse_dates=True)
    fc = pd.read_csv(EC / "spain_dayahead_hourly.csv", index_col=0, parse_dates=True)
    gen.index, fc.index = pd.to_datetime(gen.index, utc=True), pd.to_datetime(fc.index, utc=True)
    idx = pd.date_range(max(gen.index.min(), fc.index.min()), min(gen.index.max(), fc.index.max()), freq="h", tz="UTC")
    d = pd.DataFrame(index=idx)
    d["ci"] = gen["ci"].reindex(idx).interpolate(limit=3)
    for c in ("fc_solar_mw", "fc_wind_mw", "fc_load_mw", "price_eur_mwh"):
        d[c] = fc[c].reindex(idx).interpolate(limit=3)
    return d


def features(d: pd.DataFrame) -> pd.DataFrame:
    """Every lag is >= 24 h and every forecast is the day-ahead one, so all of it is known at 23:00 the day before."""
    f = pd.DataFrame(index=d.index)
    ci = d["ci"]
    f["ci"] = ci
    f["price_eur_mwh"] = d["price_eur_mwh"]            # day-ahead price: published before the day
    f["fc_solar_mw"], f["fc_wind_mw"], f["fc_load_mw"] = d["fc_solar_mw"], d["fc_wind_mw"], d["fc_load_mw"]
    f["renew_share"] = (d["fc_solar_mw"] + d["fc_wind_mw"]) / d["fc_load_mw"].replace(0, np.nan)
    f["renew_share_lag24"] = f["renew_share"].shift(24)
    idx = d.index
    f["hour"], f["dow"], f["month"] = idx.hour, idx.dayofweek, idx.month
    f["is_weekend"] = (idx.dayofweek >= 5).astype(int)
    f["hour_sin"], f["hour_cos"] = np.sin(2 * np.pi * idx.hour / 24), np.cos(2 * np.pi * idx.hour / 24)
    f["doy_sin"], f["doy_cos"] = np.sin(2 * np.pi * idx.dayofyear / 365.25), np.cos(2 * np.pi * idx.dayofyear / 365.25)
    for lag in (24, 25, 26, 48, 72, 168):
        f[f"ci_lag_{lag}"] = ci.shift(lag)
    s = ci.shift(24)
    f["ci_lag24_daymean"], f["ci_lag24_daymax"], f["ci_lag24_daymin"] = s.rolling(24).mean(), s.rolling(24).max(), s.rolling(24).min()
    f["ci_lag168_daymean"] = ci.shift(168).rolling(24).mean()
    f["ci_lag24_std"] = s.rolling(24).std()
    f["ci_trend"] = ci.shift(24) - ci.shift(168)
    return f.dropna()


def year_span(f: pd.DataFrame, a: int, b: int) -> pd.DataFrame:
    return f[(f.index.year >= a) & (f.index.year <= b)]


def score(model, train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> dict:
    model.fit(train[cols], train["ci"])
    pred = pd.Series(model.predict(test[cols]), index=test.index)
    mae = float(np.abs(pred - test["ci"]).mean())
    ev = evaluate(night_curves(test["ci"], pred, "Europe/Madrid"))
    ungated = sweep(ev, "pred_saving", [-1e9])[0]
    gated = sweep(ev, "pred_saving", [GATE_TAU])[0]
    oracle = sum(r["e_naive"] - r["e_or"] for r in ev) / sum(r["e_naive"] for r in ev) * 100
    return {"mae": round(mae, 2), "captured_pct": ungated["captured_of_oracle_pct"],
            "worse_nights_pct": ungated["worse_share_pct"],
            "gated_captured_pct": gated["captured_of_oracle_pct"], "gated_worse_pct": gated["worse_share_pct"],
            "oracle_saving_pct": round(oracle, 2), "nights": len(ev)}


def gbm():
    return HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05, max_depth=8,
                                         min_samples_leaf=40, l2_regularization=1.0, random_state=0)


def main() -> None:
    f = features(load())
    base_cols = [c for c in f.columns if c != "ci" and c not in TSO and c != "price_eur_mwh"]
    all_cols = base_cols + TSO + ["price_eur_mwh"]
    no_price = base_cols + TSO
    print(f"{len(f):,} hourly rows {f.index.min():%Y-%m-%d}..{f.index.max():%Y-%m-%d} · {len(all_cols)} features")
    res: dict = {"rows": len(f), "span": f"{f.index.min():%Y-%m-%d}..{f.index.max():%Y-%m-%d}"}

    print("\nA. Validation: the deployed split on the new source (Kaggle model: MAE 23.70, 71.0%)")
    a = score(Ridge(alpha=1.0), year_span(f, 2015, 2017), year_span(f, 2018, 2018), no_price)
    a0 = score(Ridge(alpha=1.0), year_span(f, 2015, 2017), year_span(f, 2018, 2018), base_cols)
    print(f"   with day-ahead forecasts : MAE {a['mae']}, captures {a['captured_pct']}%")
    print(f"   lags and calendar only   : MAE {a0['mae']}, captures {a0['captured_pct']}%")
    res["A_replication"] = {"with_tso": a, "without_tso": a0, "kaggle_deployed": {"mae": 23.704, "captured_pct": 71.02}}

    test = year_span(f, TEST_YEAR, TEST_YEAR)
    print(f"\nB. What the day-ahead forecasts are worth on the modern grid (train 2022-2024, test {TEST_YEAR})")
    tr = year_span(f, 2022, 2024)
    b_tso = score(Ridge(alpha=1.0), tr, test, no_price)
    b_none = score(Ridge(alpha=1.0), tr, test, base_cols)
    b_price = score(Ridge(alpha=1.0), tr, test, all_cols)
    print(f"   lags + calendar only      : MAE {b_none['mae']:>6}, captures {b_none['captured_pct']}%")
    print(f"   + day-ahead sol/wind/load : MAE {b_tso['mae']:>6}, captures {b_tso['captured_pct']}%")
    print(f"   + day-ahead price         : MAE {b_price['mae']:>6}, captures {b_price['captured_pct']}%")
    res["B_value_of_forecasts"] = {"lags_only": b_none, "with_tso": b_tso, "with_tso_and_price": b_price}

    print(f"\nC. Training window, chosen on {VALID_YEAR} then scored on {TEST_YEAR} (ridge, with day-ahead forecasts)")
    print(f"   {'years':<8} {'valid MAE':>10} {'valid capt.':>12} {'test MAE':>9} {'test capt.':>11} {'gbm test MAE':>13} {'gbm capt.':>10}")
    valid = year_span(f, VALID_YEAR, VALID_YEAR)
    rows = []
    for n in WINDOWS:
        v = score(Ridge(alpha=1.0), year_span(f, VALID_YEAR - n, VALID_YEAR - 1), valid, all_cols)
        t = score(Ridge(alpha=1.0), year_span(f, TEST_YEAR - n, TEST_YEAR - 1), test, all_cols)
        g = score(gbm(), year_span(f, TEST_YEAR - n, TEST_YEAR - 1), test, all_cols)
        rows.append({"years": n, "valid": v, "test": t, "gbm_test": g})
        print(f"   {n:<8} {v['mae']:>10} {str(v['captured_pct']) + '%':>12} {t['mae']:>9} {str(t['captured_pct']) + '%':>11} "
              f"{g['mae']:>13} {str(g['captured_pct']) + '%':>10}")
    best = min(rows, key=lambda r: r["valid"]["mae"])
    print(f"   chosen on validation MAE: {best['years']} years")
    res["C_window"] = {"rows": rows, "chosen_years": best["years"], "chosen_on": f"{VALID_YEAR} validation MAE"}

    print(f"\nD. The deployable model: ridge on {best['years']} years ending {TEST_YEAR - 1}-12-31")
    train = year_span(f, TEST_YEAR - best["years"], TEST_YEAR - 1)
    model = Ridge(alpha=1.0).fit(train[all_cols], train["ci"])
    final = score(Ridge(alpha=1.0), train, test, all_cols)
    blend_pred = (Ridge(alpha=1.0).fit(train[all_cols], train["ci"]).predict(test[all_cols])
                  + gbm().fit(train[all_cols], train["ci"]).predict(test[all_cols])) / 2
    ev = evaluate(night_curves(test["ci"], pd.Series(blend_pred, index=test.index), "Europe/Madrid"))
    blend = sweep(ev, "pred_saving", [-1e9])[0]["captured_of_oracle_pct"]
    print(f"   {TEST_YEAR}: MAE {final['mae']}, captures {final['captured_pct']}% of a {final['oracle_saving_pct']}% achievable saving; "
          f"gate at {GATE_TAU}%: captures {final['gated_captured_pct']}%, worse nights {final['worse_nights_pct']}% -> {final['gated_worse_pct']}%")
    print(f"   (ridge+GBM blend, not shipped: captures {blend}%)")
    res["D_deployed"] = {**final, "blend_captured_pct": blend, "train_years": best["years"]}

    OUT_MODEL.write_text(json.dumps({
        "description": "Day-ahead carbon-intensity forecaster for the modern Spanish grid. "
                       "prediction = intercept + sum(coef[i] * feature[i])",
        "units": "gCO2eq/kWh",
        "model": "ridge(alpha=1.0)",
        "trained_on": f"{train.index.min():%Y-%m-%d}..{train.index.max():%Y-%m-%d}",
        "tested_on": str(TEST_YEAR),
        "features": all_cols,
        "coefficients": [float(c) for c in model.coef_],
        "intercept": float(model.intercept_),
        "test_mae": final["mae"],
        "captured_pct": final["captured_pct"],
        "source": "Energy-Charts (Fraunhofer ISE), CC BY 4.0: generation and day-ahead forecasts republished from ENTSO-E",
    }, indent=2), encoding="utf-8")
    OUT_JSON.write_text(json.dumps({"note": "Generated by ml/train_modern.py", **res}, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT_MODEL.name} and {OUT_JSON.name}")


if __name__ == "__main__":
    main()
