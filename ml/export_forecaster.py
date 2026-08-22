"""Export the deployable day-ahead forecaster.

train_v2.py's strongest candidate is a ridge+GBM blend (MAE 22.61, captures
72.8% of the achievable saving). It is not what ships: the blend needs
scikit-learn at inference, while ridge alone exports as a coefficient vector
scored with a dot product and keeps the serverless bundle free of ML
dependencies. Ridge gives up ~1.8pp of captured saving for that, which is the
right trade for a function that already carries a CBC solver binary.

Weather features are deliberately excluded — measured at -0.19pp, they are
redundant with the TSO day-ahead solar and wind forecasts already in the feature
set. See FINDINGS.md.

    python export_forecaster.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "src"))
sys.path.insert(0, str(HERE.parent / "backend"))

from train_v2 import TRAIN_END, build, decision_regret  # noqa: E402

OUT = HERE / "artifacts" / "ridge_forecaster.json"
ALPHA = 1.0


def main() -> None:
    data, feats = build(with_weather=False)
    train = data.loc[:TRAIN_END]
    test = data.loc[TRAIN_END:].iloc[1:]
    X_tr, y_tr, X_te, y_te = train[feats], train["ci"], test[feats], test["ci"]

    model = Ridge(alpha=ALPHA).fit(X_tr, y_tr)
    pred = model.predict(X_te)

    mae = float(mean_absolute_error(y_te, pred))
    rmse = float(np.sqrt(mean_squared_error(y_te, pred)))
    captured = float(decision_regret(test, pred))

    coefs = [float(c) for c in model.coef_]
    intercept = float(model.intercept_)

    # The exported numbers must reproduce sklearn exactly, or the API would
    # silently serve a different model than the one that was evaluated.
    manual = X_te.to_numpy() @ np.array(coefs) + intercept
    drift = float(np.abs(manual - pred).max())
    assert drift < 1e-6, f"exported coefficients diverge from sklearn by {drift}"

    OUT.write_text(json.dumps({
        "description": "Day-ahead carbon-intensity forecaster. "
                       "prediction = intercept + sum(coef[i] * feature[i])",
        "units": "gCO2eq/kWh",
        "model": f"ridge(alpha={ALPHA})",
        "features": feats,
        "coefficients": coefs,
        "intercept": intercept,
        "trained_on": f"{train.index.min().date()}..{train.index.max().date()}",
        "tested_on": f"{test.index.min().date()}..{test.index.max().date()}",
        "test_mae": round(mae, 3),
        "test_rmse": round(rmse, 3),
        "captured_pct": round(captured, 2),
        "note": "Ridge rather than the stronger ridge+GBM blend: this exports as "
                "plain coefficients and needs no scikit-learn at inference. "
                "Weather features excluded — measured at -0.19pp, redundant with "
                "the day-ahead solar/wind forecasts already present.",
    }, indent=2), encoding="utf-8")

    print(f"features   : {len(feats)}")
    print(f"train/test : {len(train):,} / {len(test):,}")
    print(f"MAE        : {mae:.3f}   (was 28.272)")
    print(f"RMSE       : {rmse:.3f}")
    print(f"captures   : {captured:.2f}%  (was 68.50%)")
    print(f"round-trip : exact (max drift {drift:.1e})")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
