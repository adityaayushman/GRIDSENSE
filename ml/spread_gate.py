"""Does "act only when the predicted saving is large" fix scheduling-on-a-forecast?

FINDINGS.md finding 6 showed that scheduling on the day-ahead forecast captures
92-98% of the achievable saving on nights with real structure, but on nearly flat
nights forecast error exceeds the spread being chased and the schedule is *worse
than charging on arrival* (-9.4% on one night). It named the remedy and left it
unbuilt: act only when the predicted spread is large enough to survive the
model's own error.

This builds it and measures it, on the three grids the project covers.

    python spread_gate.py

**The gate.** At 18:00 the scheduler has a forecast curve for the night. It
computes the saving it *expects* — the forecast-optimal schedule against charging
on arrival, both scored on the forecast — and acts only if that expectation is at
least tau. Below tau it charges on arrival. A second rule gates on the forecast's
window spread (max-min over the mean) instead, since the finding was worded that
way; the expected saving is the decision-relevant version of the same idea.

**Forecasters.** Spain uses the deployed ridge model (the only one the project
ships), scored on its held-out 2018 year. Germany and India have no deployed
forecaster, so each gets a deliberately plain one — ridge on 24-168 hour lags and
the previous day's mean/max/min, trained on the first 70% of its record and scored
on the rest. These are weaker than Spain's (no TSO day-ahead features), so the
three grids are *not* a like-for-like forecast comparison, only a test of whether
the gate helps whatever forecaster is driving it.

**Fleet.** Identical vehicles, 9.2 kWh at 7 kW, window 18:00-07:00, the same on
every grid so only the grid differs. With no coupling constraint the problem
separates (finding 4), so one vehicle's greedy fill is the LP optimum; that is
cross-checked against the LP below. The Indian fleet is really smaller scooters
and rickshaws; it is not used here because the question is the gate, not the
fleet.

**Choosing tau without peeking.** tau is picked on the first half of the held-out
nights and reported on the second half, so the headline is not tuned on the
nights it is scored on. The full sweep over all held-out nights is also saved.
"""

from __future__ import annotations

import json
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "src"))
sys.path.insert(0, str(HERE.parent / "backend"))

from app.optimizer import Vehicle, optimize_schedule  # noqa: E402
from export_regions import DE_FACTORS  # noqa: E402
from india_carbon import hourly as india_hourly  # noqa: E402
from train_v2 import TRAIN_END, build as build_spain  # noqa: E402

OUT = HERE / "artifacts" / "spread_gate.json"
ARRIVAL, DEADLINE = 18, 7
WINDOW = [h % 24 for h in range(ARRIVAL, ARRIVAL + (24 - ARRIVAL + DEADLINE))]
ENERGY_KWH, CHARGER_KW = 9.2, 7.0
SAVING_TAUS = [0, 0.25, 0.5, 1, 1.5, 2, 3, 4, 5, 7.5, 10, 15, 20]   # percent
SPREAD_TAUS = [0, 5, 10, 15, 20, 25, 30, 40]                          # percent
TRAIN_FRACTION = 0.7


# --------------------------------------------------------------------- scheduling
def fill(curve: list[float]) -> list[float]:
    """One vehicle's emissions-optimal schedule: its cleanest hours, charger-limited."""
    sched = [0.0] * 24
    need = ENERGY_KWH
    for h in sorted(WINDOW, key=lambda x: curve[x]):
        take = min(CHARGER_KW, need)
        sched[h] = take
        need -= take
        if need <= 1e-12:
            break
    return sched


def on_arrival() -> list[float]:
    sched = [0.0] * 24
    need = ENERGY_KWH
    for h in WINDOW:
        take = min(CHARGER_KW, need)
        sched[h] = take
        need -= take
        if need <= 1e-12:
            break
    return sched


NAIVE = on_arrival()


def emis(sched: list[float], curve: list[float]) -> float:
    return sum(s * c for s, c in zip(sched, curve))


# --------------------------------------------------------------------- nights
def night_curves(actual: pd.Series, pred: pd.Series, tz: str | None) -> list[dict]:
    """Pair actual and forecast 24-slot curves per charging night (18:00 -> 07:00)."""
    idx = actual.index
    if tz and idx.tz is not None:
        idx = idx.tz_convert(tz)
    hours = idx.hour
    night = idx.normalize() - pd.to_timedelta((hours < DEADLINE).astype(int), unit="D")
    f = pd.DataFrame({"a": actual.values, "p": pred.reindex(actual.index).values, "h": hours, "n": night})
    out = []
    for n, g in f.groupby("n"):
        a, p = g.groupby("h")["a"].mean(), g.groupby("h")["p"].mean()
        if not (set(WINDOW) <= set(a.index) and set(WINDOW) <= set(p.index)):
            continue
        if a.loc[WINDOW].isna().any() or p.loc[WINDOW].isna().any():
            continue
        out.append({
            "night": str(pd.Timestamp(n).date()),
            "actual": [float(a.get(h, a.mean())) for h in range(24)],
            "forecast": [float(p.get(h, p.mean())) for h in range(24)],
        })
    return out


def evaluate(nights: list[dict]) -> list[dict]:
    rows = []
    for n in nights:
        a, f = n["actual"], n["forecast"]
        opt_f = fill(f)
        e_naive_f, e_opt_f = emis(NAIVE, f), emis(opt_f, f)
        win_f = [f[h] for h in WINDOW]
        rows.append({
            "night": n["night"],
            "e_naive": emis(NAIVE, a),
            "e_fc": emis(opt_f, a),          # scheduled on the forecast, scored on actuals
            "e_or": emis(fill(a), a),        # perfect foresight
            "pred_saving": (1 - e_opt_f / e_naive_f) * 100 if e_naive_f else 0.0,
            "pred_spread": (max(win_f) - min(win_f)) / (sum(win_f) / len(win_f)) * 100,
        })
    return rows


def sweep(rows: list[dict], key: str, taus: list[float]) -> list[dict]:
    total_naive = sum(r["e_naive"] for r in rows)
    oracle_gain = sum(r["e_naive"] - r["e_or"] for r in rows)
    out = []
    for tau in taus:
        gains, acted = [], 0
        for r in rows:
            if r[key] >= tau:
                acted += 1
                gains.append(r["e_naive"] - r["e_fc"])
            else:
                gains.append(0.0)
        real = [g / r["e_naive"] * 100 for g, r in zip(gains, rows)]
        neg = [g for g in gains if g < -1e-9]
        out.append({
            "tau": tau,
            "nights": len(rows),
            "acted": acted,
            "acted_share": round(acted / len(rows) * 100, 1),
            "median_saving_pct": round(statistics.median(real), 3),
            "total_saving_pct": round(sum(gains) / total_naive * 100, 3),
            "captured_of_oracle_pct": round(sum(gains) / oracle_gain * 100, 1) if oracle_gain > 0 else None,
            "worse_nights": len(neg),
            "worse_share_pct": round(len(neg) / len(rows) * 100, 1),
            "harm_pct_of_naive": round(-sum(neg) / total_naive * 100, 3),
        })
    return out


def pick_tau(rows: list[dict], key: str, taus: list[float]) -> float:
    """tau that maximises total emissions saved on the selection half."""
    best = max(sweep(rows, key, taus), key=lambda s: s["total_saving_pct"])
    return best["tau"]


# --------------------------------------------------------------------- forecasters
def lag_features(ci: pd.Series, idx: pd.DatetimeIndex) -> pd.DataFrame:
    df = pd.DataFrame(index=idx)
    for lag in (24, 25, 26, 48, 72, 168):
        df[f"lag{lag}"] = ci.shift(lag)
    s = ci.shift(24)
    df["daymean"], df["daymax"], df["daymin"] = s.rolling(24).mean(), s.rolling(24).max(), s.rolling(24).min()
    hh = idx.hour
    df["hsin"], df["hcos"] = np.sin(2 * np.pi * hh / 24), np.cos(2 * np.pi * hh / 24)
    df["msin"], df["mcos"] = np.sin(2 * np.pi * idx.dayofyear / 365.25), np.cos(2 * np.pi * idx.dayofyear / 365.25)
    return df


def ridge_fit_predict(ci: pd.Series, alpha: float = 1.0) -> pd.Series:
    """Plain lag ridge, trained on the first 70% of the record; returns held-out predictions."""
    full = ci.reindex(pd.date_range(ci.index.min(), ci.index.max(), freq="h")).interpolate(limit=3)
    X = lag_features(full, full.index)
    ok = X.notna().all(axis=1) & full.notna()
    X, y = X[ok], full[ok]
    cut = int(len(X) * TRAIN_FRACTION)
    mu, sd = X.iloc[:cut].mean(), X.iloc[:cut].std().replace(0, 1)
    Z = ((X - mu) / sd).to_numpy()
    A = Z[:cut]
    w = np.linalg.solve(A.T @ A + alpha * np.eye(A.shape[1]), A.T @ (y.iloc[:cut].to_numpy() - y.iloc[:cut].mean()))
    pred = Z[cut:] @ w + y.iloc[:cut].mean()
    return pd.Series(pred, index=X.index[cut:])


def spain_nights() -> tuple[list[dict], dict]:
    model = json.loads((HERE / "artifacts" / "ridge_forecaster.json").read_text(encoding="utf-8"))
    data, feats = build_spain(with_weather=False)
    assert feats == model["features"], "feature set drifted from the exported model"
    pred = pd.Series(data[feats].to_numpy() @ np.array(model["coefficients"]) + model["intercept"], index=data.index)
    test = data.loc[TRAIN_END:].iloc[1:]
    nights = night_curves(test["ci"], pred, "Europe/Madrid")
    return nights, {"forecaster": "deployed ridge (ridge_forecaster.json)", "held_out": "2018"}


def germany_nights() -> tuple[list[dict], dict]:
    d = pd.read_csv(HERE / "data/de/de_lu_hourly.csv", parse_dates=["ts_utc"]).set_index("ts_utc").sort_index()
    g = d[list(DE_FACTORS)].fillna(0.0)
    ci = (sum(g[c] * DE_FACTORS[c] for c in DE_FACTORS) / g.sum(axis=1).replace(0, np.nan)).dropna()
    ci = ci[~ci.index.duplicated()]
    pred = ridge_fit_predict(ci)
    nights = night_curves(ci.loc[pred.index], pred, "Europe/Berlin")
    return nights, {"forecaster": "lag ridge, trained on first 70%", "held_out": f"{pred.index[0]:%Y-%m-%d}..{pred.index[-1]:%Y-%m-%d}"}


def india_nights() -> tuple[list[dict], dict]:
    h = india_hourly()
    ci = h.set_index("timestamp")["ci"]
    ci = ci[~ci.index.duplicated()]
    pred = ridge_fit_predict(ci)
    nights = night_curves(ci.loc[pred.index], pred, None)
    return nights, {"forecaster": "lag ridge, trained on first 70%", "held_out": f"{pred.index[0]:%Y-%m-%d}..{pred.index[-1]:%Y-%m-%d}"}


def check_against_lp(nights: list[dict], k: int = 12) -> float:
    """Worst relative gap between the greedy fill and the LP, over k sampled nights."""
    fleet = [Vehicle("agg", ENERGY_KWH * 80, CHARGER_KW * 80, ARRIVAL, DEADLINE)]
    worst = 0.0
    for n in random.Random(0).sample(nights, min(k, len(nights))):
        c = n["actual"]
        lp = optimize_schedule(fleet, c, objective="emissions")
        e_lp = sum(lp[h] * c[h] for h in range(24)) / 80
        e_gr = emis(fill(c), c)
        worst = max(worst, abs(e_lp - e_gr) / e_gr)
    return worst


# --------------------------------------------------------------------- main
def run_grid(name: str, nights: list[dict], meta: dict) -> dict:
    gap = check_against_lp(nights)
    if gap > 1e-9:
        raise RuntimeError(f"greedy fill disagrees with the LP by {gap:.2e} on {name}; "
                           "the separability shortcut no longer holds")
    rows = evaluate(nights)
    if name == "Spain":
        # The ungated sweep must reproduce the number FINDINGS.md already publishes
        # for this forecaster, or the harness is measuring something else.
        published = json.loads((HERE / "artifacts" / "ridge_forecaster.json").read_text("utf-8"))["captured_pct"]
        got = sweep(rows, "pred_saving", [-1e9])[0]["captured_of_oracle_pct"]
        if abs(got - published) > 0.5:
            raise RuntimeError(f"ungated Spain captures {got}% but the published figure is {published}%")
    half = len(rows) // 2
    sel, rep = rows[:half], rows[half:]
    res = {"grid": name, **meta, "nights": len(rows), "greedy_vs_lp_max_rel_gap": gap,
           "sweep_saving_gate": sweep(rows, "pred_saving", SAVING_TAUS),
           "sweep_spread_gate": sweep(rows, "pred_spread", SPREAD_TAUS),
           "oracle_total_saving_pct": round(sum(r["e_naive"] - r["e_or"] for r in rows)
                                            / sum(r["e_naive"] for r in rows) * 100, 3)}
    out_of_sample = {}
    for key, taus, label in (("pred_saving", SAVING_TAUS, "saving_gate"), ("pred_spread", SPREAD_TAUS, "spread_gate")):
        tau = pick_tau(sel, key, taus)
        out_of_sample[label] = {
            "tau_chosen_on_first_half": tau,
            "selection_nights": len(sel), "reported_nights": len(rep),
            "ungated": sweep(rep, key, [0])[0],
            "gated": sweep(rep, key, [tau])[0],
        }
    res["out_of_sample"] = out_of_sample
    return res


def show(res: dict) -> None:
    print(f"\n=== {res['grid']} — {res['forecaster']}; held out {res['held_out']}; {res['nights']} nights"
          f" (greedy vs LP gap {res['greedy_vs_lp_max_rel_gap']:.1e}) ===")
    print(f"oracle (perfect foresight) total saving: {res['oracle_total_saving_pct']}%")
    print(f"{'tau%':>6} {'acted':>7} {'median':>8} {'total':>8} {'captured':>9} {'worse':>7} {'harm%':>7}")
    for s in res["sweep_saving_gate"]:
        print(f"{s['tau']:>6} {s['acted_share']:>6}% {s['median_saving_pct']:>7}% {s['total_saving_pct']:>7}% "
              f"{str(s['captured_of_oracle_pct']):>8}% {s['worse_share_pct']:>6}% {s['harm_pct_of_naive']:>7}")
    for label in ("saving_gate", "spread_gate"):
        o = res["out_of_sample"][label]
        u, g = o["ungated"], o["gated"]
        print(f"  {label}: tau={o['tau_chosen_on_first_half']} (chosen on first {o['selection_nights']} nights)"
              f" -> second {o['reported_nights']} nights: ungated total {u['total_saving_pct']}% / worse {u['worse_share_pct']}%"
              f"  vs gated total {g['total_saving_pct']}% / worse {g['worse_share_pct']}% / acted {g['acted_share']}%")


def main() -> None:
    results = []
    for name, loader in (("Spain", spain_nights), ("Germany", germany_nights), ("India", india_nights)):
        nights, meta = loader()
        res = run_grid(name, nights, meta)
        results.append(res)
        show(res)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "note": "Generated by ml/spread_gate.py",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fleet": f"identical vehicles, {ENERGY_KWH} kWh at {CHARGER_KW} kW, window {ARRIVAL:02d}:00-{DEADLINE:02d}:00",
        "grids": results,
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
