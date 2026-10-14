"""Does training the carbon forecaster for the decision it feeds beat training it for MAE?

The deployed forecaster minimises squared error over all 24 hours. The scheduler only uses the
overnight window, and only cares about the *ordering* of hours inside it. So four changes are
tried, each against the plain ridge, selected on 2024 and reported on 2025 (never selected on the
test year):

  1. OVERNIGHT ONLY   train on the charging-window hours only (18:00-07:00 local)
  2. PER-HOUR MODELS  one ridge per hour of the day, so wind can matter at 03:00 and solar at 13:00
  3. RESIDUAL LOAD    add day-ahead load minus solar minus wind, the demand dispatchable plant meets
  4. BLEND            average the best linear variant with gradient boosting

Scored by the share of the achievable saving a forecast-driven schedule captures (finding 3) and,
behind the gate at tau = 4% (finding 13), the nights it makes worse.

    python train_decision_aware.py     # -> artifacts/decision_aware.json
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

from train_modern import TSO, features, load, score, year_span  # noqa: E402

OUT = HERE / "artifacts" / "decision_aware.json"
NIGHT = set(range(18, 24)) | set(range(0, 8))     # local hours of the charging window


class PerHour:
    """One model per local hour of day. Hours with too little data fall back to a pooled model."""

    def __init__(self, make, hours=None):
        self.make, self.hours, self.models, self.pool = make, hours, {}, None

    def fit(self, X: pd.DataFrame, y: pd.Series):
        h = X["lhour"]
        cols = [c for c in X.columns if c != "lhour"]
        self.cols = cols
        self.pool = self.make().fit(X[cols], y)
        for k in sorted(h.unique()):
            if self.hours is not None and k not in self.hours:
                continue
            m = h == k
            if m.sum() >= 300:
                self.models[k] = self.make().fit(X.loc[m, cols], y[m])
        return self

    def predict(self, X: pd.DataFrame):
        out = np.empty(len(X))
        for k in X["lhour"].unique():
            m = (X["lhour"] == k).to_numpy()
            model = self.models.get(k, self.pool)
            out[m] = model.predict(X.loc[m, self.cols])
        return out


class Overnight:
    """Fit on window hours only; predict anywhere."""

    def __init__(self, make):
        self.make = make

    def fit(self, X, y):
        m = X["lhour"].isin(NIGHT)
        self.cols = [c for c in X.columns if c != "lhour"]
        self.model = self.make().fit(X.loc[m, self.cols], y[m])
        return self

    def predict(self, X):
        return self.model.predict(X[self.cols])


class Blend:
    def __init__(self, a, b):
        self.a, self.b = a, b

    def fit(self, X, y):
        self.a.fit(X, y)
        self.b.fit(X, y)
        return self

    def predict(self, X):
        return (np.asarray(self.a.predict(X)) + np.asarray(self.b.predict(X))) / 2


class Plain:
    def __init__(self, make):
        self.make = make

    def fit(self, X, y):
        self.cols = [c for c in X.columns if c != "lhour"]
        self.model = self.make().fit(X[self.cols], y)
        return self

    def predict(self, X):
        return self.model.predict(X[self.cols])


def ridge():
    return Ridge(alpha=1.0)


def gbm():
    return HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05, max_depth=8,
                                         min_samples_leaf=40, l2_regularization=1.0, random_state=0)


def build() -> tuple[pd.DataFrame, list[str], list[str]]:
    d = load()
    f = features(d)
    f["lhour"] = f.index.tz_convert("Europe/Madrid").hour
    f["fc_resid_mw"] = f["fc_load_mw"] - f["fc_solar_mw"] - f["fc_wind_mw"]
    f["fc_resid_lag24"] = f["fc_resid_mw"].shift(24)
    f = f.dropna()
    base = [c for c in f.columns if c not in ("ci", "price_eur_mwh", "lhour", "fc_resid_mw", "fc_resid_lag24") and c not in TSO]
    cols = base + TSO + ["price_eur_mwh"]
    return f, cols, cols + ["fc_resid_mw", "fc_resid_lag24"]


def main() -> None:
    f, cols, cols_resid = build()
    print(f"{len(f):,} rows · {len(cols)} features ({len(cols_resid)} with residual load)")
    variants = {
        "ridge (deployed)": (lambda: Plain(ridge), cols),
        "1 overnight only": (lambda: Overnight(ridge), cols),
        "2 per-hour ridges": (lambda: PerHour(ridge), cols),
        "3 per-hour + residual load": (lambda: PerHour(ridge), cols_resid),
        "3b ridge + residual load": (lambda: Plain(ridge), cols_resid),
        "gbm": (lambda: Plain(gbm), cols_resid),
        "4 blend: per-hour+resid & gbm": (lambda: Blend(PerHour(ridge), Plain(gbm)), cols_resid),
    }
    out: dict = {"note": "Generated by ml/train_decision_aware.py", "rows": len(f), "variants": {}}
    folds = {
        "valid 2024 (train 2023)": (year_span(f, 2023, 2023), year_span(f, 2024, 2024)),
        "test 2025 (train 2024)": (year_span(f, 2024, 2024), year_span(f, 2025, 2025)),
        "test 2025 (train 2022-24)": (year_span(f, 2022, 2024), year_span(f, 2025, 2025)),
        "2018 (train 2015-17)": (year_span(f, 2015, 2017), year_span(f, 2018, 2018)),
    }
    for name, (make, cs) in variants.items():
        out["variants"][name] = {}
        line = []
        for fold, (tr, te) in folds.items():
            keep = list(cs) + ["lhour"]
            r = score(make(), tr, te, keep)
            out["variants"][name][fold] = r
            line.append(f"{fold.split(' (')[0]}{'*' if '22-24' in fold else ''} {r['captured_pct']:>5}%/{r['mae']:>5}")
        print(f"{name:<32} " + " | ".join(line), flush=True)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
