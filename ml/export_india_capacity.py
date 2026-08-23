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
from india_load import (  # noqa: E402
    SEASONS, hourly_shape, load as load_demand, season_levels, window_flatness,
)

OUT = HERE.parent / "frontend" / "src" / "data" / "india.json"

#: Homes behind one distribution transformer.
#:
#: This was guessed at 40 first, which was wrong in a way that mattered: it put
#: the houses at 15 kW under a 90 kW unit — 17% loaded — and a transformer that
#: empty hides every effect worth measuring, seasonal variation included.
#: A 100 kVA distribution transformer in India is normally sized for 70-80 kW,
#: and utilities aim for 60-75% loading. At the ~0.385 kW per-home peak implied
#: by measured Delhi consumption, that is roughly 150-180 homes.
HOMES = 150

#: Delhi's average electrified household, ~260 kWh/month. Chosen over the
#: national mean of 98 because EV ownership concentrates in exactly the urban,
#: higher-consumption households this figure describes.
DAILY_KWH_PER_HOME = 260 * 12 / 365

ARRIVAL, DEADLINE = 18, 7


def residential_baseline(homes: int, shape: list[float],
                         daily_kwh: float = DAILY_KWH_PER_HOME,
                         level: float = 1.0) -> list[float]:
    """A feeder profile with a measured shape and a measured magnitude.

    `shape` comes from 46,728 hours of Grid-India demand, normalised so only its
    form survives; `daily_kwh` pins the level to measured household consumption;
    `level` carries the season. Nothing here is drawn by hand, which is the whole
    point — the Spanish equivalent was, and it was wrong sevenfold.

    The residual assumption is that a residential feeder follows *system* demand.
    It does not exactly: residential load is peakier, because industry runs flat
    around the clock. That makes this profile optimistic about evening headroom
    rather than conservative, and the capacity figures inherit that.
    """
    scale = daily_kwh * level / sum(shape)
    return [round(s * scale * homes, 3) for s in shape]


def main() -> None:
    demand = load_demand()
    window_hours = [h % 24 for h in range(ARRIVAL, ARRIVAL + (24 - ARRIVAL + DEADLINE))]
    annual_shape = hourly_shape(demand)
    levels = season_levels(demand, window=window_hours)
    flatness = window_flatness(demand, window=window_hours)

    base = residential_baseline(HOMES, annual_shape)
    res_peak = max(base)
    res_daily = sum(base)
    ratings_kw = dt_ratings_kw()

    print(f"{HOMES} homes · {DAILY_KWH_PER_HOME:.1f} kWh/home/day · "
          f"residential peak {res_peak:.1f} kW · {res_daily:.0f} kWh/day\n")

    # A flat carbon curve: this question is about power against a rating, and
    # nothing here depends on which hour is cleanest. Using a real curve would
    # imply the answer moves with carbon, and it does not.
    carbon = [250.0] * 24

    def dumb_capacity(rating: float, base: list[float] = base) -> int:
        """Largest fleet whose charge-on-arrival peak still fits under the rating."""
        best = 0
        for n in range(1, 4001):
            peak = max(naive_schedule(indian_fleet(n))[h] + base[h] for h in range(24))
            if peak <= rating:
                best = n
            else:
                return best
        raise RuntimeError(f"dumb sweep hit its 4000 bound at {rating:.0f} kW")

    def coordinated_capacity(rating: float, base: list[float] = base) -> int:
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

    # ---- seasonal sweep -------------------------------------------------
    # Capacity is not one number. Indian overnight demand runs 23% higher in
    # summer than in late autumn and the window is flatter, so the transformer
    # is most stressed exactly when coordination has least valley to exploit.
    hk_head = headline["rating_kw"]
    seasonal = []
    print()
    print(f"Seasonal, on the {headline['rating_kva']} kVA unit "
          "(shape and level both measured):")
    print(f"{'season':<10}{'level':>7}{'pk/val':>8}{'res peak':>10}{'dumb':>7}"
          f"{'coord':>8}{'gain':>7}")
    print("-" * 57)
    for name in SEASONS:
        sb = residential_baseline(HOMES, hourly_shape(demand, months=SEASONS[name]),
                                  level=levels[name])
        sp = max(sb)
        if sp >= hk_head:
            seasonal.append({"season": name, "level": levels[name],
                             "peak_valley": flatness[name],
                             "residential_peak_kw": round(sp, 1),
                             "dumb": 0, "coordinated": 0, "gain": None,
                             "overloaded": True})
            print(f"{name:<10}{levels[name]:>7.2f}{flatness[name]:>8.2f}{sp:>10.1f}"
                  "   houses alone exceed the rating")
            continue
        sd = dumb_capacity(hk_head, sb)
        sc = coordinated_capacity(hk_head, sb)
        seasonal.append({
            "season": name, "level": levels[name], "peak_valley": flatness[name],
            "residential_peak_kw": round(sp, 1), "dumb": sd, "coordinated": sc,
            "gain": round(sc / max(sd, 1), 1), "overloaded": False,
        })
        print(f"{name:<10}{levels[name]:>7.2f}{flatness[name]:>8.2f}{sp:>10.1f}"
              f"{sd:>7}{sc:>8}{sc / max(sd, 1):>6.1f}x")

    ok = [r for r in seasonal if not r["overloaded"]]
    worst = min(ok, key=lambda r: r["coordinated"]) if ok else None
    best = max(ok, key=lambda r: r["coordinated"]) if ok else None
    if worst and best:
        print()
        print(f"  worst season {worst['season']} ({worst['coordinated']} vehicles) - "
              f"best {best['season']} ({best['coordinated']}) - "
              f"spread {best['coordinated'] / max(worst['coordinated'], 1):.2f}x")
        print("  A transformer sized on an annual average is sized for the wrong month.")

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
        "seasonal": seasonal,
        "seasonal_worst": worst,
        "seasonal_best": best,
        "demand_source": {
            "rows": 46728,
            "range": "2019-01-01..2024-04-30",
            "origin": "Grid-India hourly demand via Kaggle "
                      "shubhamvashisht/hourly-load-india-electrical-load-forecasting",
            "lag1_autocorr": 0.979,
        },
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
