"""How many Indian EVs fit under an Indian distribution transformer.

The hosting-capacity question never needed carbon data — it is load against a
rating — so it is the part of this project that transfers to India directly,
and it is the part that matters most there. Indian distribution transformers are
63 to 250 kVA where the European model assumes 1,250 kW, and the vehicles under
them are scooters and rickshaws rather than cars.

The residential baseline here is calibrated to measured consumption rather than
drawn freehand: Delhi households average about 260 kWh a month, so the profile
is scaled to that daily energy and only its *shape* is assumed. The shape is
still an assumption and remains the weakest input, but the magnitude no longer
is. (The Spanish baseline in `app/data_sources.py` is not calibrated this way
and overstates household demand about sevenfold — see FINDINGS.)

    python export_india_capacity.py
"""

from __future__ import annotations

import json
import math
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "src"))
sys.path.insert(0, str(HERE.parent / "backend"))

from app.optimizer import Vehicle, naive_schedule, optimize_schedule  # noqa: E402
from india_fleet import (  # noqa: E402
    DT_RATINGS_KVA, POWER_FACTOR, SEGMENTS, dt_ratings_kw, fleet_summary, indian_fleet,
)

OUT = HERE.parent / "frontend" / "src" / "data" / "india.json"

#: Homes behind one distribution transformer. Indian DTs serve far fewer
#: consumers than European feeders; 40 is typical for a 100 kVA urban unit.
HOMES = 40

#: Delhi's average electrified household, ~260 kWh/month. Chosen over the
#: national mean of 98 because EV ownership concentrates in exactly the urban,
#: higher-consumption households this figure describes.
DAILY_KWH_PER_HOME = 260 * 12 / 365

ARRIVAL, DEADLINE = 18, 7


def residential_baseline(homes: int, daily_kwh: float = DAILY_KWH_PER_HOME) -> list[float]:
    """A household profile whose *energy* is measured and whose shape is assumed.

    Indian residential demand peaks hard in the evening — lighting, fans and
    air conditioning arriving together — with a smaller morning bump and a low
    overnight floor. The curve below is normalised and then scaled so the day
    integrates to the measured consumption, which keeps the one thing that can
    be checked honest even though the shape cannot be.
    """
    shape = [
        0.55
        + 1.35 * math.exp(-((h - 20) ** 2) / 6.0)   # evening peak, ~20:00
        + 0.40 * math.exp(-((h - 8) ** 2) / 3.0)    # morning bump
        for h in range(24)
    ]
    scale = daily_kwh / sum(shape)
    return [round(s * scale * homes, 3) for s in shape]


def main() -> None:
    base = residential_baseline(HOMES)
    res_peak = max(base)
    res_daily = sum(base)
    ratings_kw = dt_ratings_kw()

    print(f"{HOMES} homes · {DAILY_KWH_PER_HOME:.1f} kWh/home/day · "
          f"residential peak {res_peak:.1f} kW · {res_daily:.0f} kWh/day\n")

    # A flat carbon curve: this question is about power against a rating, and
    # nothing here depends on which hour is cleanest. Using a real curve would
    # imply the answer moves with carbon, and it does not.
    carbon = [250.0] * 24

    def dumb_capacity(rating: float) -> int:
        """Largest fleet whose charge-on-arrival peak still fits under the rating."""
        best = 0
        for n in range(1, 4001):
            peak = max(naive_schedule(indian_fleet(n))[h] + base[h] for h in range(24))
            if peak <= rating:
                best = n
            else:
                return best
        raise RuntimeError(f"dumb sweep hit its 4000 bound at {rating:.0f} kW")

    def coordinated_capacity(rating: float) -> int:
        """Largest fleet the scheduler can fit, by bisection on the solver."""
        headroom = sum(max(rating - b, 0.0) for b in base)
        mean_need = sum(
            SEGMENTS[s]["energy_kwh"] * w
            for s, w in (("e2w", .564), ("e3w", .351), ("ecar", .078))
        )
        bound = int(1.6 * headroom / mean_need) + 50
        lo, hi = 0, bound
        while lo < hi:
            mid = (lo + hi + 1) // 2
            try:
                optimize_schedule(indian_fleet(mid), carbon,
                                  residential_baseline_kw=base,
                                  feeder_capacity_kw=rating)
                lo = mid
            except ValueError:
                hi = mid - 1
        if lo >= bound:
            raise RuntimeError(
                f"bisection bound {bound} reached at {rating:.0f} kW — the true "
                "ceiling is above the range searched"
            )
        return lo

    rows = []
    print(f"{'rating':>12} {'headroom':>10} {'dumb':>7} {'coordinated':>12} {'gain':>7}")
    print("-" * 54)
    for kva, kw in zip(DT_RATINGS_KVA, ratings_kw):
        if kw <= res_peak:
            print(f"{kva:>7} kVA  {'—':>10} {'0':>7} {'0':>12}   houses alone exceed it")
            rows.append({"rating_kva": kva, "rating_kw": kw, "dumb": 0,
                         "coordinated": 0, "gain": None, "overloaded": True})
            continue
        d = dumb_capacity(kw)
        c = coordinated_capacity(kw)
        rows.append({
            "rating_kva": kva, "rating_kw": kw, "dumb": d, "coordinated": c,
            "gain": round(c / max(d, 1), 1), "overloaded": False,
        })
        print(f"{kva:>7} kVA  {kw - res_peak:>9.1f}kW {d:>7} {c:>12} "
              f"{c / max(d, 1):>6.1f}×")

    headline = next((r for r in rows if r["rating_kva"] == 100 and not r["overloaded"]),
                    next((r for r in rows if not r["overloaded"]), None))
    if headline is None:
        raise RuntimeError("every rating was overloaded by the baseline alone")

    # The same transformer, asked to carry European cars instead.
    def euro_fleet(n: int) -> list[Vehicle]:
        return [Vehicle(f"c{i}", 9.2, 7.0, (ARRIVAL + (i % 4)) % 24, DEADLINE)
                for i in range(n)]

    hk = headline["rating_kw"]
    euro_dumb = 0
    for n in range(1, 2001):
        if max(naive_schedule(euro_fleet(n))[h] + base[h] for h in range(24)) <= hk:
            euro_dumb = n
        else:
            break

    summary = fleet_summary(100)
    print(f"\nOn the {headline['rating_kva']} kVA unit: {headline['dumb']} vehicles "
          f"charging on arrival, {headline['coordinated']} coordinated "
          f"({headline['gain']}×).")
    print(f"The same transformer takes only {euro_dumb} European cars on arrival.")
    print(f"\n100 Indian EVs want {summary['total']['energy_kwh']} kWh and "
          f"{summary['total']['connected_kw']} kW connected;\n"
          f"100 European cars would want 920 kWh and 700 kW.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "note": "Generated by ml/export_india_capacity.py — do not edit by hand.",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_rev": (subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE,
                                   capture_output=True, text=True).stdout.strip() or None),
        "homes": HOMES,
        "daily_kwh_per_home": round(DAILY_KWH_PER_HOME, 2),
        "residential_peak_kw": round(res_peak, 1),
        "residential_daily_kwh": round(res_daily, 1),
        "power_factor": POWER_FACTOR,
        "window": f"{ARRIVAL:02d}:00-{DEADLINE:02d}:00",
        "fleet_mix_source": "FADA retail registrations, calendar 2025",
        "segments": {k: {**v} for k, v in SEGMENTS.items()},
        "fleet_per_100": summary,
        "euro_comparison": {
            "rating_kva": headline["rating_kva"],
            "indian_dumb": headline["dumb"],
            "euro_dumb": euro_dumb,
            "energy_per_100_indian_kwh": summary["total"]["energy_kwh"],
            "energy_per_100_euro_kwh": 920.0,
            "connected_per_100_indian_kw": summary["total"]["connected_kw"],
            "connected_per_100_euro_kw": 700.0,
        },
        "headline": headline,
        "ratings": rows,
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
