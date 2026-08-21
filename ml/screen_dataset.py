"""Screen a candidate time-series dataset before training anything on it.

Written after three suggested datasets turned out to be untrainable — one was a
notebook rather than data, one had no time column at all, and one was
independent random draws per row wearing timestamps. Each would have produced a
model that learned the mean and reported a plausible-looking error.

The decisive test is autocorrelation. Any real physical series — grid load,
charging demand, temperature — is strongly correlated hour to hour, because
physical systems have inertia. Values drawn independently are not, no matter how
realistic the column names and ranges look.

    python screen_dataset.py <csv> --time <col> [--value <col> ...]

Exits non-zero if the data fails, so it can gate a pipeline.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

# Below this, a series carries no more hour-to-hour memory than white noise.
LAG1_FLOOR = 0.30


def autocorr(s: pd.Series, lag: int) -> float:
    s = pd.to_numeric(s, errors="coerce").dropna()
    return float(s.autocorr(lag)) if len(s) > lag + 2 else float("nan")


def screen(path: str, time_col: str, value_cols: list[str]) -> bool:
    df = pd.read_csv(path)
    if time_col not in df.columns:
        print(f"FAIL  no time column '{time_col}' — columns: {list(df.columns)[:12]}")
        return False

    df[time_col] = pd.to_datetime(df[time_col], errors="coerce", utc=True)
    df = df.dropna(subset=[time_col]).sort_values(time_col)

    if not value_cols:
        value_cols = [
            c for c in df.select_dtypes("number").columns
            if not c.lower().endswith("id") and df[c].nunique() > 10
        ]
    print(f"{path}\n  rows {len(df):,} · {df[time_col].min()} -> {df[time_col].max()}")

    gaps = df[time_col].diff().dropna()
    if len(gaps):
        step = gaps.mode().iloc[0]
        print(f"  modal step {step} · irregular steps "
              f"{int((gaps != step).sum())}/{len(gaps)}")

    rng = np.random.default_rng(0)
    noise = pd.Series(rng.uniform(size=len(df)))
    print(f"  white-noise reference lag-1 {autocorr(noise, 1):+.3f}\n")

    print(f"  {'column':<34} {'lag-1':>8} {'lag-2':>8} {'lag-24':>8}   verdict")
    print("  " + "-" * 72)
    verdicts = []
    for c in value_cols:
        a1, a2, a24 = (autocorr(df[c], l) for l in (1, 2, 24))
        ok = not np.isnan(a1) and abs(a1) >= LAG1_FLOOR
        verdicts.append(ok)
        print(f"  {c:<34} {a1:>+8.3f} {a2:>+8.3f} {a24:>+8.3f}   "
              f"{'real signal' if ok else 'INDISTINGUISHABLE FROM NOISE'}")

    passed = any(verdicts)
    print()
    if passed:
        print(f"PASS  at least one column carries hour-to-hour memory (lag-1 >= {LAG1_FLOOR})")
    else:
        print(f"FAIL  every column has lag-1 below {LAG1_FLOOR}: values are effectively")
        print("      independent draws. A model fit to this learns the mean and nothing")
        print("      else, while still reporting a believable error figure.")
    return passed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--time", required=True)
    ap.add_argument("--value", action="append", default=[])
    args = ap.parse_args()
    sys.exit(0 if screen(args.csv, args.time, args.value) else 1)


if __name__ == "__main__":
    main()
