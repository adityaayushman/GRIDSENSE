"""Does a longer, more recent Spanish record make the forecaster better?

`fetch_spain_ec.py` extends the Spanish generation record from 2015-2018 to
2015-2026 (Energy-Charts). That record has no TSO day-ahead solar / wind / load
forecasts, which the deployed model leans on, so it can only be compared fairly
after separating three questions that a single retrain would blur:

  A. Source and features. Same split as the deployed model (train 2015-2017, test
     2018) on the new source, with lag/calendar features only. This isolates what
     the missing TSO forecasts cost, and checks the new source against the old.
  B. Drift. The 2015-2017 model scored on 2025. Spain's grid has changed a great
     deal since 2018, so this says whether the shipped model describes today.
  C. Data volume on the modern grid. Train on the 1, 2, 3, 5, 8 and 10 years
     before 2025 and score on 2025. If error keeps falling, more data is the
     lever; if it flattens, it is not.

Everything is scored by decision regret (the share of the achievable saving a
forecast-driven schedule captures, finding 3), not only by MAE.

    python train_long.py
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

CSV = HERE / "data" / "es-ec" / "spain_hourly.csv"
OUT = HERE / "artifacts" / "long_dataset.json"
TEST_YEAR = 2025


def load() -> pd.DataFrame:
    d = pd.read_csv(CSV, index_col=0, parse_dates=True)
    d.index = pd.to_datetime(d.index, utc=True)
    d = d.reindex(pd.date_range(d.index.min(), d.index.max(), freq="h", tz="UTC"))
    d["ci"] = d["ci"].interpolate(limit=3)
    d["load"] = d["Load"].interpolate(limit=3)
    return d


def features(d: pd.DataFrame) -> pd.DataFrame:
    """Lag and calendar features only — every lag is >= 24h, so it is known at 23:00 the day before."""
    f = pd.DataFrame(index=d.index)
    ci = d["ci"]
    f["ci"] = ci
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
    # Realised demand a day and a week ago stands in for the TSO load forecast.
    f["load_lag_24"], f["load_lag_168"] = d["load"].shift(24), d["load"].shift(168)
    return f.dropna()


def score(model, train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> dict:
    model.fit(train[cols], train["ci"])
    pred = pd.Series(model.predict(test[cols]), index=test.index)
    mae = float(np.abs(pred - test["ci"]).mean())
    rows = evaluate(night_curves(test["ci"], pred, "Europe/Madrid"))
    s = sweep(rows, "pred_saving", [-1e9])[0]
    oracle = sum(r["e_naive"] - r["e_or"] for r in rows) / sum(r["e_naive"] for r in rows) * 100
    return {"mae": round(mae, 2), "captured_pct": s["captured_of_oracle_pct"],
            "nights": len(rows), "oracle_saving_pct": round(oracle, 2)}


def span(f: pd.DataFrame, start_year: int, end_year: int) -> pd.DataFrame:
    return f[(f.index.year >= start_year) & (f.index.year <= end_year)]


def main() -> None:
    d = load()
    f = features(d)
    cols = [c for c in f.columns if c != "ci"]
    ci = d["ci"].dropna()
    lag1 = float(ci.autocorr(1))
    print(f"{len(d):,} hourly rows {d.index.min():%Y-%m-%d}..{d.index.max():%Y-%m-%d} · "
          f"ci mean {ci.mean():.0f} · lag-1 autocorr {lag1:.3f} · {len(cols)} features")

    # Year-by-year grid character, so the drift is visible and not just asserted.
    yearly = {int(y): {"mean_ci": round(float(g.mean()), 1), "std_ci": round(float(g.std()), 1)}
              for y, g in ci.groupby(ci.index.year)}
    print("  mean ci by year: " + ", ".join(f"{y}:{v['mean_ci']:.0f}" for y, v in yearly.items()))

    results: dict = {"rows": len(d), "span": f"{d.index.min():%Y-%m-%d}..{d.index.max():%Y-%m-%d}",
                     "lag1_autocorr": round(lag1, 3), "yearly": yearly, "features": cols}

    print("\nA. Same split as the deployed model, new source, no TSO forecasts")
    a = score(Ridge(alpha=1.0), span(f, 2015, 2017), span(f, 2018, 2018), cols)
    print(f"   train 2015-2017 -> test 2018: MAE {a['mae']}, captures {a['captured_pct']}%"
          f"   (deployed Kaggle model: MAE 23.70, 71.0%)")
    results["A_same_split"] = a

    test = span(f, TEST_YEAR, TEST_YEAR)
    print(f"\nB. Drift: the 2015-2017 model on {TEST_YEAR}")
    b = score(Ridge(alpha=1.0), span(f, 2015, 2017), test, cols)
    print(f"   MAE {b['mae']}, captures {b['captured_pct']}%  (oracle saving that year {b['oracle_saving_pct']}%)")
    results["B_drift"] = b

    print(f"\nC. Training volume on the modern grid, test {TEST_YEAR}")
    print(f"   {'training years':<18} {'rows':>7} {'ridge MAE':>10} {'ridge capt.':>12} {'gbm MAE':>9} {'gbm capt.':>10}")
    curve = []
    for n_years in (1, 2, 3, 5, 8, 10):
        start = TEST_YEAR - n_years
        train = span(f, start, TEST_YEAR - 1)
        r = score(Ridge(alpha=1.0), train, test, cols)
        g = score(HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05, max_depth=8,
                                                min_samples_leaf=40, l2_regularization=1.0, random_state=0),
                  train, test, cols)
        curve.append({"train_years": n_years, "train_span": f"{start}-{TEST_YEAR - 1}", "rows": len(train),
                      "ridge": r, "gbm": g})
        print(f"   {start}-{TEST_YEAR - 1} ({n_years:>2}y)    {len(train):>7,} {r['mae']:>10} {str(r['captured_pct']) + '%':>12} "
              f"{g['mae']:>9} {str(g['captured_pct']) + '%':>10}")
    results["C_volume"] = curve
    results["test_year"] = TEST_YEAR

    OUT.write_text(json.dumps({"note": "Generated by ml/train_long.py", **results}, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
