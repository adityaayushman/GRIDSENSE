"""How much transformer headroom does imperfect baseline forecasting cost? (India, 100 kVA, 150 homes.)

Coordinated charging is scheduled against a *forecast* of the street's other demand. The 123-vehicle figure
of finding 10 assumes that forecast is perfect. A distribution company would schedule on a day-ahead
estimate and be judged on what the transformer actually carries. This measures the price of the gap:

  1. Hold back a margin m of the rating when scheduling (feeder limit = rating x (1 - m)).
  2. Schedule the fleet against a baseline forecast that is the true baseline times (1 + e), where e is an
     hourly error with standard deviation s and hour-to-hour correlation 0.7 (day-ahead errors persist).
  3. Score it against the TRUE baseline: an overload is any hour above the rating.

For each error level s, the smallest margin whose overload probability stays at or under 5% is found, and
the fleet the unit hosts at that margin is reported.

Error levels: 3% is the national day-ahead demand forecast's own error (`train_india.py`, MAPE 2.4-2.5%,
which is ~3% as a standard deviation). A single feeder is much harder to forecast than a nation; the
5, 10 and 20% levels are GUESSES that bracket plausible feeder-level error, since no Indian feeder
forecasting error is published that I could find. Treat them as a sensitivity, not a measurement.

    python india_robustness.py        # -> artifacts/india_robustness.json, frontend and backend copies
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import export_india_capacity as ic  # noqa: E402

OUTS = [HERE / "artifacts" / "india_robustness.json",
        HERE.parent / "frontend" / "src" / "data" / "india_robustness.json",
        HERE.parent / "backend" / "app" / "data" / "india_robustness.json"]
RATING_KVA = 100
SIGMAS = [0.0, 0.03, 0.05, 0.10, 0.20]
MARGINS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30]
DRAWS = 60
RHO = 0.7
TARGET = 0.05
CARBON = [250.0] * 24


def coordinated_capacity(base: list[float], cap_kw: float) -> int:
    headroom = sum(max(cap_kw - b, 0.0) for b in base)
    mean_need = sum(ic.SEGMENTS[s]["energy_kwh"] * w for s, w in (("e2w", .564), ("e3w", .351), ("ecar", .078)))
    lo, hi = 0, int(1.6 * headroom / mean_need) + 50
    while lo < hi:
        mid = (lo + hi + 1) // 2
        try:
            ic.optimize_schedule(ic.indian_fleet(mid), CARBON, residential_baseline_kw=base, feeder_capacity_kw=cap_kw)
            lo = mid
        except ValueError:
            hi = mid - 1
    return lo


def noise(sigma: float, rng: np.random.Generator) -> np.ndarray:
    """AR(1) hourly multiplicative error with stationary std `sigma`."""
    e = np.zeros(24)
    e[0] = rng.normal(0, sigma)
    for h in range(1, 24):
        e[h] = RHO * e[h - 1] + rng.normal(0, sigma * np.sqrt(1 - RHO ** 2))
    return e


def overload_probability(n: int, base: list[float], cap_kw: float, rating_kw: float, sigma: float, seed: int) -> float:
    if sigma == 0:
        draws = 1
    else:
        draws = DRAWS
    rng = np.random.default_rng(seed)
    fleet = ic.indian_fleet(n)
    bad = 0
    for _ in range(draws):
        e = noise(sigma, rng) if sigma else np.zeros(24)
        forecast = [b * (1 + x) for b, x in zip(base, e)]
        try:
            sched = ic.optimize_schedule(fleet, CARBON, residential_baseline_kw=forecast, feeder_capacity_kw=cap_kw)
        except ValueError:
            bad += 1                                   # could not even be scheduled on the forecast
            continue
        load = [sched.hourly_optimized_load_kw[h] if hasattr(sched, "hourly_optimized_load_kw") else sched[h] for h in range(24)]
        if max(load[h] + base[h] for h in range(24)) > rating_kw + 1e-6:
            bad += 1
    return bad / draws


def main() -> None:
    demand = ic.load_demand()
    base = ic.residential_baseline(ic.HOMES, ic.hourly_shape(demand))
    rating = ic.dt_ratings_kw()[ic.DT_RATINGS_KVA.index(RATING_KVA)]
    caps = {m: coordinated_capacity(base, rating * (1 - m)) for m in MARGINS}
    print("capacity by margin:", caps, flush=True)
    rows = []
    for s in SIGMAS:
        probs = {}
        for m in MARGINS:
            probs[m] = overload_probability(caps[m], base, rating * (1 - m), rating, s, seed=int(s * 1000) + int(m * 100))
        ok = [m for m in MARGINS if probs[m] <= TARGET]
        best = min(ok) if ok else None
        rows.append({
            "error_sd_pct": round(s * 100), "label": {0.0: "perfect forecast", 0.03: "national day-ahead demand error"}.get(s, "assumed feeder-level error"),
            "overload_prob_by_margin": {f"{int(m * 100)}": round(probs[m], 3) for m in MARGINS},
            "margin_needed_pct": None if best is None else int(best * 100),
            "capacity_at_margin": None if best is None else caps[best],
        })
        r = rows[-1]
        print(f"  error {r['error_sd_pct']:>2}%: margin needed {r['margin_needed_pct']}% -> {r['capacity_at_margin']} EVs   {r['overload_prob_by_margin']}", flush=True)
    out = {
        "note": "Generated by ml/india_robustness.py - sensitivity to an assumed forecast error, not a measurement.",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rating_kva": RATING_KVA, "homes": ic.HOMES, "draws": DRAWS, "target_overload_prob": TARGET,
        "error_correlation": RHO,
        "capacity_by_margin": {f"{int(m * 100)}": c for m, c in caps.items()},
        "dumb": 35, "perfect_forecast_capacity": caps[0.0],
        "rows": rows,
        "caveats": ["3% is the national forecast's own error; the 5, 10 and 20% rows are guesses at feeder-level error.",
                    "Errors are multiplicative on the whole baseline with hour-to-hour correlation 0.7.",
                    "One night shape, the annual mean; no seasonal or day-of-week variation."],
    }
    text = json.dumps(out, indent=1)
    for p in OUTS:
        p.write_text(text, encoding="utf-8")
    print("wrote", OUTS[0])


if __name__ == "__main__":
    main()
