"""Rolling-horizon control: re-solve every hour, commit only the next one.

The scheduler elsewhere in this project decides the whole night at 18:00 from a
single forecast. Real grid operators do not work that way — they re-solve as new
data arrives and commit only the imminent step, because a forecast for 03:00
made at 18:00 is worse than one made at 02:00. train_horizon.py measures exactly
that: MAE rises from 6.7 g at one hour ahead to 26.3 g at thirteen.

Four strategies are replayed over every complete night in the held-out year and
all four are scored against *actual* carbon intensity:

  naive      charge on arrival at full power
  one-shot   best forecast available at 18:00, solved once, executed in full
  mpc        re-solve each hour on refreshed forecasts, execute one hour
  oracle     perfect foresight; the floor on achievable emissions

The one-shot baseline gets the *best* forecast obtainable at 18:00 — the lag
models where they win, the day-ahead model beyond the crossover at h=9. Handing
it a deliberately worse forecast would manufacture an MPC advantage out of model
selection rather than control.

The measure is regret: how much worse than perfect foresight, in gCO2. MPC is
worth its complexity only if it closes a real share of the one-shot regret.

    python mpc.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "src"))
sys.path.insert(0, str(HERE.parent / "backend"))

from app.optimizer import Vehicle, _available_hours, naive_schedule, optimize_schedule  # noqa: E402
from carbon import carbon_intensity  # noqa: E402
from train_horizon import EXOG, MAX_HORIZON, TRAIN_END, build, load_frame  # noqa: E402
from train_v2 import build as build_day_ahead  # noqa: E402

HORIZON_MODEL = HERE / "artifacts" / "horizon_forecaster.json"
DAY_AHEAD_MODEL = HERE / "artifacts" / "ridge_forecaster.json"
OUT = HERE.parent / "frontend" / "src" / "data" / "mpc.json"

ARRIVAL, DEADLINE = 18, 7
WINDOW = [h % 24 for h in range(ARRIVAL, ARRIVAL + (24 - ARRIVAL + DEADLINE))]
EV_COUNT, ENERGY_KWH, CHARGER_KW = 80, 9.2, 7.0
FLEET_KWH, FLEET_KW = ENERGY_KWH * EV_COUNT, CHARGER_KW * EV_COUNT


class HorizonForecaster:
    """Per-horizon ridge models, applied to whatever is observable at hour t."""

    def __init__(self, path: Path) -> None:
        spec = json.loads(path.read_text(encoding="utf-8"))
        self.features: list[str] = spec["features"]
        self.max_h: int = spec["max_horizon"]
        self.models = {
            int(h): (np.array(m["coefficients"], dtype=float), float(m["intercept"]))
            for h, m in spec["horizons"].items()
        }
        self.mae = {int(h): m["test_mae"] for h, m in spec["horizons"].items()}

    def predict(self, feats: np.ndarray, h: int) -> float:
        coef, intercept = self.models[h]
        return float(feats @ coef + intercept)


def day_ahead_predictions(path: Path) -> tuple[pd.Series, float]:
    """The shipped day-ahead model, scored over every hour it can reach.

    Its lags are all 24h or longer, so a prediction for any hour is available the
    previous day and does not improve as that hour approaches. That is precisely
    what makes it the right belief for the far end of the window, and what makes
    it useless as a source of MPC advantage.
    """
    spec = json.loads(path.read_text(encoding="utf-8"))
    data, feats = build_day_ahead(with_weather=False)
    coef = np.array(spec["coefficients"], dtype=float)
    if list(feats) != list(spec["features"]):
        raise RuntimeError("day-ahead feature order does not match the exported model")
    pred = data[feats].to_numpy(float) @ coef + float(spec["intercept"])
    return pd.Series(pred, index=data.index), float(spec["test_mae"])


def emissions(load: list[float], actual: list[float]) -> float:
    return sum(l * c for l, c in zip(load, actual))


def solve_from(hour: int, remaining_kwh: float, curve: list[float]) -> list[float]:
    """LP over the hours still ahead, for the energy still owed."""
    if remaining_kwh <= 1e-9:
        return [0.0] * 24
    v = Vehicle("agg", remaining_kwh, FLEET_KW, hour, DEADLINE)
    return optimize_schedule([v], curve, objective="emissions")


#: Deferral penalties tried, in units of the horizon's own forecast MAE. The diagnosis
#: (FINDINGS.md finding 9) is that the minimum of a dozen noisy forecasts is
#: optimistically biased, so the controller keeps waiting for a clean hour that
#: turns out to be ordinary. Adding lambda * MAE(h) to a forecast h hours out prices
#: that optionality: farther, less certain hours must look cleaner by more to be
#: worth waiting for. lambda = 0 is the unmodified controller.
PENALTIES = (0.0, 0.5, 1.0, 1.5, 2.0)


def solve_from_fast(hour: int, remaining_kwh: float, curve: list[float]) -> list[float]:
    """The same plan as `solve_from`, by greedy fill.

    With one aggregated fleet and no coupling constraint the problem separates, so
    the cheapest-hours-first fill is the LP optimum (finding 4). Used for the
    penalty sweep, which needs ~10x more solves than the original arms; the control
    in main() checks it against the LP.
    """
    plan = [0.0] * 24
    if remaining_kwh <= 1e-9:
        return plan
    left = remaining_kwh
    for h in sorted(_available_hours(Vehicle("agg", remaining_kwh, FLEET_KW, hour, DEADLINE)),
                    key=lambda x: curve[x]):
        take = min(FLEET_KW, left)
        plan[h] = take
        left -= take
        if left <= 1e-12:
            break
    return plan


def run_mpc_fast(window_hours: list[int], forecasts: dict[int, list[float]]) -> list[float]:
    load = [0.0] * 24
    remaining = FLEET_KWH
    for h in window_hours:
        if remaining <= 1e-9:
            break
        plan = solve_from_fast(h, remaining, forecasts.get(h, forecasts[window_hours[0]]))
        commit = min(plan[h], remaining, FLEET_KW)
        load[h] = commit
        remaining -= commit
    return load


def penalised(believed: dict[int, list[float]], lam: float, mae_at,
              window_hours: list[int]) -> dict[int, list[float]]:
    """Add lam * (forecast MAE at that horizon) to every forecast hour still ahead."""
    out = {}
    for i, t in enumerate(window_hours):
        curve = list(believed[t])
        for j in range(i, len(window_hours)):
            curve[window_hours[j]] += lam * mae_at(j - i + 1)
        out[t] = curve
    return out


def run_mpc(window_hours: list[int], actual: list[float],
            forecasts: dict[int, list[float]]) -> list[float]:
    """Re-solve at every hour; keep only the hour about to happen.

    `forecasts[t]` is the 24-hour curve believed at decision hour t: measured
    values for hours already past, predictions for hours still ahead.
    """
    load = [0.0] * 24
    remaining = FLEET_KWH

    for i, h in enumerate(window_hours):
        if remaining <= 1e-9:
            break
        # Solving even the final hour through the LP keeps the charger power cap
        # enforced everywhere; special-casing it would let the tail exceed FLEET_KW.
        plan = solve_from(h, remaining, forecasts.get(h, forecasts[window_hours[0]]))
        commit = min(plan[h], remaining, FLEET_KW)
        load[h] = commit
        remaining -= commit

    if remaining > 1e-6:
        raise RuntimeError(
            f"MPC left {remaining:.3f} kWh undelivered — the rolling solves "
            "deferred more than the remaining window could absorb"
        )
    return load


def main() -> None:
    hf = HorizonForecaster(HORIZON_MODEL)
    da_pred, day_ahead_mae = day_ahead_predictions(DAY_AHEAD_MODEL)

    # The horizon beyond which the static day-ahead model is the better forecast.
    crossover = next((h for h in range(1, hf.max_h + 1) if hf.mae[h] > day_ahead_mae),
                     hf.max_h + 1)
    print(f"day-ahead MAE {day_ahead_mae:.2f} · lag models win out to h={crossover - 1}, "
          f"day-ahead beyond\n")

    df = load_frame()
    # Precompute every horizon's feature matrix once; indexed by decision hour.
    feats = {h: build(df, h)[0] for h in range(1, MAX_HORIZON + 1)}

    test = df.index > pd.Timestamp(TRAIN_END, tz="UTC")
    local = df.index.tz_convert("Europe/Madrid")
    night = local.normalize() - pd.to_timedelta((local.hour < DEADLINE).astype(int), unit="D")
    df = df.assign(_night=night, _hour=local.hour, _test=test)

    fleet = [Vehicle("agg", FLEET_KWH, FLEET_KW, ARRIVAL, DEADLINE)]
    naive = naive_schedule(fleet)

    rows = []
    for _, grp in df[df["_test"]].groupby("_night"):
        # A DST fall-back night has two 02:00 hours; average them so each clock
        # hour appears once.
        by_hour = grp.groupby("_hour")["ci"].mean()
        if not set(WINDOW).issubset(by_hour.index):
            continue

        fallback = float(by_hour.mean())
        actual = [float(by_hour.get(h, fallback)) for h in range(24)]
        # Earliest timestamp per clock hour, for looking up that hour's features.
        ts_of = {int(h): g.index.min() for h, g in grp.groupby("_hour")}

        # What is believed at each decision hour: measured for hours already
        # finished, forecast for the current hour and everything after it.
        #
        # The decision covering hour t is taken as hour t-1 closes, so the
        # controller knows intensities through t-1 and must forecast t itself at
        # one hour ahead. Reading the current hour's true value instead would
        # hand every strategy a free measurement it could not have.
        believed: dict[int, list[float]] = {}
        ok = True
        for i, t in enumerate(WINDOW):
            if t not in ts_of:
                ok = False
                break
            base = ts_of[t] - pd.Timedelta(hours=1)  # last hour fully observed
            curve = list(actual)
            for j in range(i, len(WINDOW)):
                tgt, h = WINDOW[j], j - i + 1
                if h > MAX_HORIZON or base not in feats[h].index:
                    ok = False
                    break
                if h < crossover:
                    curve[tgt] = hf.predict(feats[h].loc[base].to_numpy(float), h)
                else:
                    # Beyond the crossover the static day-ahead model is more
                    # accurate than the lag models, so a competent controller
                    # uses it — and so does the one-shot baseline.
                    tgt_ts = ts_of.get(tgt)
                    if tgt_ts is None or tgt_ts not in da_pred.index:
                        ok = False
                        break
                    curve[tgt] = float(da_pred.loc[tgt_ts])
            if not ok:
                break
            believed[t] = curve
        if not ok:
            continue

        # A third arm that re-solves every hour but never learns anything: the
        # day-ahead belief for every future hour, refreshed only by hours turning
        # from forecast into measurement. Comparing it against `mpc` separates
        # what rolling *commitment* costs from what fresher information buys.
        static: dict[int, list[float]] = {}
        for i, t in enumerate(WINDOW):
            curve = list(actual)
            for j in range(i, len(WINDOW)):
                tgt_ts = ts_of.get(WINDOW[j])
                if tgt_ts is None or tgt_ts not in da_pred.index:
                    ok = False
                    break
                curve[WINDOW[j]] = float(da_pred.loc[tgt_ts])
            if not ok:
                break
            static[t] = curve
        if not ok:
            continue

        # One-shot: everything believed at 18:00, committed in full.
        oneshot = solve_from(ARRIVAL, FLEET_KWH, believed[ARRIVAL])
        mpc = run_mpc(WINDOW, actual, believed)
        oracle = solve_from(ARRIVAL, FLEET_KWH, actual)
        # Control: the same rolling machinery on perfect forecasts. Rolling
        # commitment is time-consistent under perfect information, so this must
        # reproduce the oracle. If it does not, the loss below is a bug, not a
        # property of forecasting. Sampled — it costs a full extra solve per
        # hour and one night in ten is enough to catch a structural error.
        mpc_static = run_mpc(WINDOW, actual, static)
        mae_at = lambda k: hf.mae[k] if k < crossover else day_ahead_mae  # noqa: E731
        pen = {lam: run_mpc_fast(WINDOW, penalised(believed, lam, mae_at, WINDOW)) for lam in PENALTIES}
        check = len(rows) % 25 == 0
        mpc_perfect = run_mpc(WINDOW, actual, {h: actual for h in WINDOW}) if check else None

        # Every strategy must deliver the same energy under the same power cap,
        # or the emissions comparison is meaningless.
        for name, sched in (("oneshot", oneshot), ("mpc", mpc),
                            ("mpc_static", mpc_static), ("oracle", oracle),
                            *((f"pen_{lam}", s) for lam, s in pen.items())):
            if abs(sum(sched) - FLEET_KWH) > 1e-3:
                raise RuntimeError(f"{name} delivered {sum(sched):.3f} of {FLEET_KWH} kWh")
            if max(sched) > FLEET_KW + 1e-6:
                raise RuntimeError(f"{name} drew {max(sched):.1f} kW over the {FLEET_KW} cap")

        e = {k: emissions(v, actual) for k, v in
             (("naive", naive), ("oneshot", oneshot), ("mpc", mpc),
              ("mpc_static", mpc_static), ("oracle", oracle))}
        for lam, sched in pen.items():
            e[f"pen_{lam}"] = emissions(sched, actual)
            e[f"pos_pen_{lam}"] = sum(i * sched[h] for i, h in enumerate(WINDOW)) / FLEET_KWH
        if mpc_perfect is not None:
            e["mpc_perfect"] = emissions(mpc_perfect, actual)
        if e["naive"] <= 0:
            continue
        # Mean position in the window at which energy lands, to see whether a
        # strategy systematically defers.
        for k, sched in (("oneshot", oneshot), ("mpc", mpc),
                         ("mpc_static", mpc_static), ("oracle", oracle)):
            e[f"pos_{k}"] = sum(i * sched[h] for i, h in enumerate(WINDOW)) / FLEET_KWH
        rows.append(e)

    if not rows:
        print("no complete nights in the held-out period")
        return

    n = len(rows)

    def cut(k: str) -> list[float]:
        return [(1 - r[k] / r["naive"]) * 100 for r in rows]

    def regret(k: str) -> list[float]:
        return [(r[k] - r["oracle"]) / r["naive"] * 100 for r in rows]

    checked = [r for r in rows if "mpc_perfect" in r]
    gap = max(abs(r["mpc_perfect"] - r["oracle"]) / max(r["oracle"], 1.0) for r in checked)
    print(f"{n} held-out nights")
    print(f"control ({len(checked)} nights): rolling solves on perfect forecasts differ "
          f"from the one-shot oracle by at most {gap * 100:.4f}% — "
          f"{'machinery is sound' if gap < 1e-6 else 'IMPLEMENTATION BUG'}\n")
    labels = (("oneshot", "one-shot"), ("mpc_static", "roll/static"),
              ("mpc", "roll/fresh"), ("oracle", "oracle"))

    print(f"{'strategy':<12} {'median cut':>11} {'mean cut':>10} "
          f"{'mean regret':>12} {'position':>9}")
    for k, label in labels:
        print(f"{label:<12} {statistics.median(cut(k)):>10.2f}% "
              f"{statistics.mean(cut(k)):>9.2f}% {statistics.mean(regret(k)):>11.3f}% "
              f"{statistics.mean(r[f'pos_{k}'] for r in rows):>9.2f}")
    print("  (position: mean hour-index at which energy lands, 0 = 18:00, 12 = 06:00)")

    r1 = statistics.mean(regret("oneshot"))
    rs = statistics.mean(regret("mpc_static"))
    rm = statistics.mean(regret("mpc"))
    closed = (1 - rm / r1) * 100 if r1 > 0 else 0.0
    wins = sum(1 for r in rows if r["mpc"] < r["oneshot"] - 1e-6)
    ties = sum(1 for r in rows if abs(r["mpc"] - r["oneshot"]) <= 1e-6)

    # The two arms differ in exactly one thing each, so the regret difference
    # attributes cleanly.
    print(f"\n  one-shot -> rolling, same information : {rs - r1:+.3f}pp  "
          f"(cost of committing hour by hour)")
    print(f"  rolling, static -> rolling, refreshed: {rm - rs:+.3f}pp  "
          f"(value of a better forecast)")
    print(f"  net                                  : {rm - r1:+.3f}pp")

    print(f"\n  MPC closes    {closed:.1f}% of the gap to perfect foresight")
    print(f"  MPC better on {wins}/{n} nights · identical on {ties} · "
          f"worse on {n - wins - ties}")

    # ---- the deferral penalty ------------------------------------------
    # Control first: lambda = 0 through the greedy solver must reproduce the LP
    # controller, or the sweep is measuring the solver and not the penalty.
    tie_gap = max(abs(r["pen_0.0"] - r["mpc"]) / r["naive"] for r in rows)
    print("\ndeferral penalty (lambda x horizon MAE added to forecasts of hours still ahead)")
    print(f"  control: lambda=0 via greedy vs the LP controller differ by at most {tie_gap * 100:.4f}% of naive")
    print(f"  {'lambda':>7} {'mean regret':>12} {'vs one-shot':>12} {'position':>9} {'better/same/worse than one-shot':>34}")
    pen_summary = {}
    for lam in PENALTIES:
        k = f"pen_{lam}"
        rg = statistics.mean(regret(k))
        b = sum(1 for r in rows if r[k] < r["oneshot"] - 1e-6)
        s = sum(1 for r in rows if abs(r[k] - r["oneshot"]) <= 1e-6)
        pen_summary[str(lam)] = {
            "mean_regret_pct": round(rg, 3), "vs_oneshot_pp": round(rg - r1, 3),
            "mean_position": round(statistics.mean(r[f"pos_{k}"] for r in rows), 2),
            "better": b, "same": s, "worse": n - b - s,
        }
        print(f"  {lam:>7} {rg:>11.3f}% {rg - r1:>+11.3f}pp {pen_summary[str(lam)]['mean_position']:>9.2f} "
              f"{b:>12}/{s}/{n - b - s}")
    best_lam = min(PENALTIES, key=lambda l: statistics.mean(regret(f"pen_{l}")))
    print(f"  best lambda {best_lam}: regret {statistics.mean(regret(f'pen_{best_lam}')):.3f}% "
          f"against one-shot {r1:.3f}%")

    if closed < 5:
        print("\n  Refreshing the forecast helps; committing hour by hour costs more")
        print("  than it buys. The one-shot LP stays the better design on this grid.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "note": "Generated by ml/mpc.py — do not edit by hand.",
        "nights": n,
        "window": f"{ARRIVAL:02d}:00-{DEADLINE:02d}:00",
        "tested_on": f"after {TRAIN_END}, held out from forecaster training",
        "crossover_horizon": crossover,
        "horizon_mae": {str(h): hf.mae[h] for h in range(1, MAX_HORIZON + 1)},
        "day_ahead_mae": day_ahead_mae,
        "strategies": {
            k: {
                "median_cut_pct": round(statistics.median(cut(k)), 2),
                "mean_cut_pct": round(statistics.mean(cut(k)), 2),
                "mean_regret_pct": round(statistics.mean(regret(k)), 3),
                "median_regret_pct": round(statistics.median(regret(k)), 3),
                # Mean hour-index at which energy lands; 0 = 18:00, 12 = 06:00.
                "mean_position": (
                    round(statistics.mean(r[f"pos_{k}"] for r in rows), 2)
                    if f"pos_{k}" in rows[0] else None
                ),
            }
            for k in ("naive", "oneshot", "mpc_static", "mpc", "oracle")
        },
        "attribution_pp": {
            "rolling_commitment": round(rs - r1, 3),
            "fresher_forecast": round(rm - rs, 3),
            "net": round(rm - r1, 3),
        },
        "deferral_penalty": {"lambdas": list(PENALTIES), "greedy_vs_lp_gap_pct": round(tie_gap * 100, 5),
                             "results": pen_summary, "best_lambda": best_lam,
                             "oneshot_regret_pct": round(r1, 3)},
        "mpc_closes_gap_pct": round(closed, 1),
        "mpc_better_nights": wins,
        "mpc_tied_nights": ties,
        "mpc_worse_nights": n - wins - ties,
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
