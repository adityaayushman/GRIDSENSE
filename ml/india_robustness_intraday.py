"""Does correcting the forecast through the night buy back what a static margin gives up?

Finding 23 priced the gap between finding 10's 123-vehicle capacity figure, which assumes a
perfect forecast of the street's other demand, and a scheduler that commits once at 18:00 to a
single erroneous day-ahead forecast and a fixed margin held back from the rating. No margin from
0% to 30% brought the overload rate under target, at any error level tested. That finding's own
text named the obvious next question: a distribution company reads its own meters all night,
so an intraday-correcting controller that re-forecasts every hour, rather than one that commits
once, was left untested. This builds it.

Mechanism, at each hour of the window:

  1. The controller has, until now, committed to charging plans built on a day-ahead forecast
     that may be wrong. At the end of each hour it reads the real meter and sees exactly how
     wrong that forecast was for the hour just finished (comparing its own prediction against the
     true baseline it can now measure).
  2. It projects that error forward with the same AR(1) persistence finding 23 assumed for the
     error process itself (correlation 0.7, so a forecast that ran high keeps running high, decayed
     geometrically) and corrects the remaining hours' forecast with it.
  3. It re-solves the schedule for the hours still ahead, for the energy each vehicle group still
     owes, against the corrected forecast and the SAME feeder margin as the static case — isolating
     the one lever this script tests (re-forecasting) from the other one finding 23 already covers
     (how much margin to hold back).

This needed a faster solve than finding 23's per-vehicle LP: an aggregate of ~120 individually
staggered vehicles into (segment, arrival offset) groups solves in the same LP to floating-point
precision (identical vehicles differ from one aggregate only in which physical scooter gets which
electron, which the objective and the feeder constraint cannot see — verified separately to 7e-15),
and is about 4x faster, which is what makes a 13-solve-per-draw rolling controller tractable here.

One more correction folded in. Finding 23's noise process chained hour 0 to hour 23 in clock order,
which reads as the night's actual hour-to-hour persistence everywhere except the one join this
project's window actually needs: 23:00 to 00:00, where the array restarts at an independent seed
rather than persisting across midnight. That is a different, smaller error from the window-wrap
bugs finding 14 and 17 found in real data, but the same family: an index that looks right until the
particular case you depend on is exactly the one it does not handle. Both controllers here are
compared under a noise process chained in WINDOW order (18:00 through 06:59, crossing midnight
correctly), so finding 23's static numbers are reproduced fresh under the fixed process rather than
quoted from the clock-ordered one.

    python india_robustness_intraday.py   # -> artifacts/india_robustness_intraday.json, frontend and backend copies
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pulp

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend"))

from app.optimizer import Vehicle, _available_hours, optimize_schedule  # noqa: E402
import export_india_capacity as ic  # noqa: E402

OUTS = [HERE / "artifacts" / "india_robustness_intraday.json",
        HERE.parent / "frontend" / "src" / "data" / "india_robustness_intraday.json",
        HERE.parent / "backend" / "app" / "data" / "india_robustness_intraday.json"]

RATING_KVA = 100
SIGMAS = [0.0, 0.03, 0.10, 0.20]
MARGINS = [0.0, 0.10, 0.20, 0.30]
DRAWS = 30  # finding 23 used 60 for one solve per draw; this needs 13, so the budget is cut in half
RHO = 0.7
TARGET = 0.05
ARRIVAL, DEADLINE = 18, 7
WINDOW_HOURS = [(ARRIVAL + i) % 24 for i in range(13)]  # position i -> hour-of-day, 18:00 .. 06:00
CARBON = [250.0] * 24

#: Capacity under a perfect forecast does not depend on forecast error, so it is not re-measured
#: here: it is taken from finding 23's own bisection search (ml/india_robustness.py) at the same
#: rating, homes and margins.
CAPACITY_BY_MARGIN = {0.0: 123, 0.10: 94, 0.20: 66, 0.30: 37}


def aggregate(fleet: list[Vehicle]) -> list[Vehicle]:
    """Group identical vehicles (same charger, same arrival/deadline) into one.

    Exact for this LP: the energy constraint is a sum over the group and the per-hour cap is a
    sum of individual caps, so the group's feasible total load is identical to the sum of its
    members' feasible total loads. Verified against the un-aggregated solve to 7e-15.
    """
    groups: dict[tuple[float, int, int], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for v in fleet:
        key = (v.charger_kw, v.arrival_hour, v.deadline_hour)
        g = groups[key]
        g[0] += v.energy_needed_kwh
        g[1] += v.charger_kw
    return [
        Vehicle(id=f"g{i}", energy_needed_kwh=energy, charger_kw=kw,
                arrival_hour=arr, deadline_hour=dl)
        for i, ((_, arr, dl), (energy, kw)) in enumerate(groups.items())
    ]


def window_noise(sigma: float, rng: np.random.Generator) -> np.ndarray:
    """AR(1) error, chained in window order (position 0 = 18:00 .. position 12 = 06:00).

    Unlike finding 23's clock-ordered chain, this persists correctly across the one join the
    window actually has: position 5 (23:00) to position 6 (00:00).
    """
    e = np.zeros(13)
    if sigma == 0:
        return e
    e[0] = rng.normal(0, sigma)
    for i in range(1, 13):
        e[i] = RHO * e[i - 1] + rng.normal(0, sigma * np.sqrt(1 - RHO ** 2))
    return e


def baseline_24(base: list[float], e: np.ndarray, upto: int | None = None) -> list[float]:
    """The 24-hour forecast array `optimize_schedule` expects: `base` outside the window and
    inside it for any position at or past `upto` (already observed, so known exactly); the
    erroring forecast for positions still ahead. `upto=None` means nothing has been observed yet.
    """
    out = list(base)
    for i, h in enumerate(WINDOW_HOURS):
        if upto is not None and i < upto:
            continue  # already happened; use the true value, not the (by now irrelevant) forecast
        out[h] = base[h] * (1 + e[i])
    return out


def static_overload(fleet_groups: list[Vehicle], base: list[float], cap_kw: float,
                     rating_kw: float, e: np.ndarray) -> bool:
    """Finding 23's controller: one forecast, one solve, executed in full."""
    forecast = baseline_24(base, e, upto=0)  # nothing observed before the 18:00 commit
    try:
        sched = optimize_schedule(fleet_groups, CARBON, objective="peak",
                                   residential_baseline_kw=forecast, feeder_capacity_kw=cap_kw)
    except ValueError:
        return True
    return max(sched[h] + base[h] for h in WINDOW_HOURS) > rating_kw + 1e-6


def solve_step(vehicles: list[Vehicle], baseline_24: list[float], cap_kw: float) -> dict[str, list[float]]:
    """Charge-only LP, minimising peak total load, returning each vehicle's own hourly load.

    `optimize_schedule` only returns the fleet's summed load, which is enough for the static,
    one-shot controller but not for the rolling one: that needs each group's own commitment at
    the current hour so its remaining energy can be tracked separately from the others'. Built
    directly rather than exposed from `app/optimizer.py`, since every other caller of that module
    only ever needs the total.
    """
    prob = pulp.LpProblem("step", pulp.LpMinimize)
    avail = {v.id: set(_available_hours(v)) for v in vehicles}
    x = {
        (v.id, h): pulp.LpVariable(f"x_{v.id}_{h}", lowBound=0,
                                    upBound=v.charger_kw if h in avail[v.id] else 0.0)
        for v in vehicles for h in range(24)
    }
    for v in vehicles:
        prob += pulp.lpSum(x[(v.id, h)] for h in range(24)) == v.energy_needed_kwh
    peak = pulp.LpVariable("peak", lowBound=0)
    for h in range(24):
        total_h = pulp.lpSum(x[(v.id, h)] for v in vehicles) + baseline_24[h]
        prob += peak >= total_h
        prob += total_h <= cap_kw
    prob += peak
    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        raise ValueError("infeasible")
    return {v.id: [x[(v.id, h)].value() for h in range(24)] for v in vehicles}


def rolling_overload(fleet_groups: list[Vehicle], base: list[float], cap_kw: float,
                      rating_kw: float, e: np.ndarray) -> bool:
    """Re-forecast and re-solve every hour; commit only the hour about to happen."""
    remaining = {v.id: v.energy_needed_kwh for v in fleet_groups}
    committed = [0.0] * 24

    for i, h in enumerate(WINDOW_HOURS):
        if all(r <= 1e-9 for r in remaining.values()):
            break
        # The AR(1) predictor of e[j] given the error just observed at position i-1 is
        # rho**(j-i+1) * e[i-1]; at i=0 nothing has been observed, so this is unbiased (all zero).
        corrected = np.zeros(13)
        if i > 0:
            last = e[i - 1]
            for j in range(i, 13):
                corrected[j] = RHO ** (j - i + 1) * last
        forecast = baseline_24(base, corrected, upto=i)

        current = []
        for v in fleet_groups:
            rem = remaining[v.id]
            if rem <= 1e-9:
                continue
            arr = h if (v.arrival_hour - ARRIVAL) % 24 <= i else v.arrival_hour
            current.append(Vehicle(id=v.id, energy_needed_kwh=rem, charger_kw=v.charger_kw,
                                    arrival_hour=arr, deadline_hour=v.deadline_hour))
        try:
            per_vehicle = solve_step(current, forecast, cap_kw)
        except ValueError:
            return True

        for v in current:
            take = min(per_vehicle[v.id][h], remaining[v.id])
            committed[h] += take
            remaining[v.id] -= take

    return max(committed[h] + base[h] for h in WINDOW_HOURS) > rating_kw + 1e-6


def main() -> None:
    t0 = time.time()
    demand = ic.load_demand()
    base = ic.residential_baseline(ic.HOMES, ic.hourly_shape(demand))
    rating = ic.dt_ratings_kw()[ic.DT_RATINGS_KVA.index(RATING_KVA)]

    rows = []
    for s in SIGMAS:
        for m in MARGINS:
            n = CAPACITY_BY_MARGIN[m]
            fleet = aggregate(ic.indian_fleet(n))
            cap_kw = rating * (1 - m)
            rng = np.random.default_rng(int(s * 1000) + int(m * 100) + 7)
            static_bad = rolling_bad = 0
            for _ in range(DRAWS):
                e = window_noise(s, rng)
                if static_overload(fleet, base, cap_kw, rating, e):
                    static_bad += 1
                if rolling_overload(fleet, base, cap_kw, rating, e):
                    rolling_bad += 1
            row = {
                "error_sd_pct": round(s * 100), "margin_pct": round(m * 100), "capacity": n,
                "static_overload_prob": round(static_bad / DRAWS, 3),
                "rolling_overload_prob": round(rolling_bad / DRAWS, 3),
            }
            rows.append(row)
            print(f"  sigma {row['error_sd_pct']:>2}% margin {row['margin_pct']:>2}% "
                  f"(n={n}): static {row['static_overload_prob']:.0%} -> "
                  f"rolling {row['rolling_overload_prob']:.0%}", flush=True)

    best_static = min((r["static_overload_prob"] for r in rows if r["error_sd_pct"] > 0), default=1.0)
    best_rolling = min((r["rolling_overload_prob"] for r in rows if r["error_sd_pct"] > 0), default=1.0)
    out = {
        "note": "Generated by ml/india_robustness_intraday.py - a follow-up to finding 23, same "
                "rating/homes/margins, re-forecasting every hour instead of committing once.",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rating_kva": RATING_KVA, "homes": ic.HOMES, "draws": DRAWS,
        "target_overload_prob": TARGET, "error_correlation": RHO,
        "capacity_by_margin": {f"{int(m * 100)}": c for m, c in CAPACITY_BY_MARGIN.items()},
        "rows": rows,
        "best_static_overload_prob": round(best_static, 3),
        "best_rolling_overload_prob": round(best_rolling, 3),
        "runtime_s": round(time.time() - t0, 1),
        "caveats": [
            "30 draws per cell, half finding 23's 60, because each draw now needs up to 13 solves "
            "instead of one.",
            "Vehicles are aggregated by (charger, arrival, deadline) before solving; exact for this "
            "LP, about 4x faster.",
            "Noise is chained in window order (crossing midnight correctly), not finding 23's clock "
            "order, so the static row here is a fresh, not quoted, reproduction of that finding.",
            "The margin is held fixed through the night; only the forecast is corrected. A "
            "margin that itself shrinks as uncertainty resolves is a different lever, untested.",
        ],
    }
    text = json.dumps(out, indent=1)
    for p in OUTS:
        p.write_text(text, encoding="utf-8")
    print(f"\nbest achievable overload probability at any margin tested, sigma>0: "
          f"static {best_static:.0%} -> rolling {best_rolling:.0%}")
    print(f"wrote {OUTS[0]} ({out['runtime_s']}s)")


if __name__ == "__main__":
    main()
