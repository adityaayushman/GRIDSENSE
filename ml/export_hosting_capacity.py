"""How many EVs can one street transformer host, under each charging strategy?

"Hosting capacity" is the question a distribution planner actually asks: given
this transformer, how much EV adoption can this feeder absorb before it needs
replacing? It reframes the project from "how much CO2 does shifting save" to
"how much grid does coordination buy you", which is the question with money
attached.

Three strategies, swept over adoption into a *fixed* neighbourhood — the houses
already exist and EVs arrive into them:

  dumb          every car charges at full power on arrival
  uncoordinated every household independently targets the cleanest hours,
                with no knowledge of its neighbours (a per-vehicle greedy fill,
                which is what a fleet of independent charging apps produces)
  coordinated   one LP schedules the street against the transformer limit

Peaks are the median across every measured night, so a single unusual evening
cannot set the headline.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "backend"))

from app import data_sources as ds  # noqa: E402
from app.optimizer import (  # noqa: E402
    Vehicle, naive_schedule, optimize_schedule, _available_hours,
)

OUT = HERE.parent / "frontend" / "src" / "data" / "hosting.json"

HOMES = 200
ENERGY_KWH, CHARGER_KW = 9.2, 7.0
ARRIVAL, DEADLINE = 18, 7
ADOPTION = list(range(0, 201, 10))
RATINGS = [1000, 1250, 1500]        # typical street-transformer ratings, kW
HEADLINE_RATING = 1250


def uncoordinated(vehicles, carbon):
    """Each household independently fills its own cleanest available hours."""
    load = [0.0] * 24
    for v in vehicles:
        need = v.energy_needed_kwh
        for h in sorted(_available_hours(v), key=lambda x: carbon[x]):
            if need <= 1e-9:
                break
            take = min(v.charger_kw, need)
            load[h] += take
            need -= take
    return load


def fleet(n: int) -> list[Vehicle]:
    """Identical vehicles aggregate exactly for these objectives, so one variable
    per hour stands in for n cars and the sweep stays fast."""
    if n == 0:
        return []
    return [Vehicle("agg", ENERGY_KWH * n, CHARGER_KW * n, ARRIVAL, DEADLINE)]


def main() -> None:
    base = ds.get_residential_baseline_kw(HOMES)
    residential_peak = max(base)
    days = ds.available_days()

    curve = []
    for n in ADOPTION:
        vs = fleet(n)
        dumb_pks, unco_pks = [], []
        coord = {str(r): [] for r in RATINGS}

        for day in days:
            carbon = ds.get_carbon_intensity(day=day)
            dumb = naive_schedule(vs) if n else [0.0] * 24
            unco = uncoordinated(vs, carbon) if n else [0.0] * 24
            dumb_pks.append(max(dumb[h] + base[h] for h in range(24)))
            unco_pks.append(max(unco[h] + base[h] for h in range(24)))

            for r in RATINGS:
                if n == 0:
                    coord[str(r)].append(residential_peak)
                    continue
                try:
                    sched = optimize_schedule(
                        vs, carbon, residential_baseline_kw=base, feeder_capacity_kw=float(r)
                    )
                    coord[str(r)].append(max(sched[h] + base[h] for h in range(24)))
                except ValueError:
                    coord[str(r)].append(None)  # physically impossible at this rating

        row = {
            "evs": n,
            "dumb_kw": round(statistics.median(dumb_pks), 1),
            "uncoordinated_kw": round(statistics.median(unco_pks), 1),
        }
        for r in RATINGS:
            vals = [v for v in coord[str(r)] if v is not None]
            feasible = len(vals) == len(days)
            row[f"coordinated_{r}_kw"] = round(statistics.median(vals), 1) if vals else None
            row[f"coordinated_{r}_feasible"] = feasible
        curve.append(row)

    def coordinated_ceiling(rating: int) -> int:
        """Largest fleet that physically fits under the rating, found analytically.

        Sweeping the LP only to 200 EVs would report 200 as the capacity when it
        is merely where the sweep stopped. max_deliverable_kwh bounds the energy
        that fits under the limit once the residential baseline is subtracted, so
        scanning it finds the real ceiling in milliseconds. It is a necessary
        condition, so the LP is spot-checked against it below.
        """
        from app.optimizer import max_deliverable_kwh

        best = 0
        for n in range(1, 3001):
            if ENERGY_KWH * n <= max_deliverable_kwh(fleet(n), base, float(rating)):
                best = n
            else:
                break
        return best

    def capacity(key: str, rating: int) -> int | None:
        """Largest adoption level whose median peak still fits under the rating."""
        ok = [r["evs"] for r in curve if r.get(key) is not None and r[key] <= rating]
        return max(ok) if ok else None

    capacities = []
    for r in RATINGS:
        coord_ok = [
            row["evs"] for row in curve
            if row.get(f"coordinated_{r}_feasible") and row.get(f"coordinated_{r}_kw") is not None
        ]
        ceiling = coordinated_ceiling(r)
        # Verify the analytic ceiling against the solver at the boundary: the
        # fleet at the ceiling must schedule, the one past it must not.
        def solves(n: int) -> bool:
            try:
                optimize_schedule(fleet(n), ds.get_carbon_intensity(day=days[0]),
                                  residential_baseline_kw=base, feeder_capacity_kw=float(r))
                return True
            except ValueError:
                return False

        capacities.append({
            "rating_kw": r,
            "dumb": capacity("dumb_kw", r),
            "uncoordinated": capacity("uncoordinated_kw", r),
            "coordinated": ceiling,
            "coordinated_verified": solves(ceiling) and not solves(ceiling + 40),
            "swept_to": ADOPTION[-1],
        })

    head = next(c for c in capacities if c["rating_kw"] == HEADLINE_RATING)
    bundle = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_rev": (subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE,
                                   capture_output=True, text=True).stdout.strip() or None),
        "note": "Generated by ml/export_hosting_capacity.py — do not edit by hand.",
        "homes": HOMES,
        "residential_peak_kw": round(residential_peak, 1),
        "nights": len(days),
        "ratings": RATINGS,
        "headline_rating_kw": HEADLINE_RATING,
        "headline": head,
        "capacities": capacities,
        "curve": curve,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(bundle, indent=2), encoding="utf-8")

    print(f"{HOMES} homes · residential peak {residential_peak:.0f} kW · {len(days)} nights\n")
    print(f"{'rating':>8} {'dumb':>8} {'uncoord':>9} {'coordinated':>13}")
    print("-" * 42)
    for c in capacities:
        co = c["coordinated"]
        print(f"{c['rating_kw']:>6} kW {str(c['dumb']):>8} {str(c['uncoordinated']):>9} "
              f"{str(co):>13}")
    print(f"\nAt {HEADLINE_RATING} kW: coordination hosts "
          f"{head['coordinated']} EVs vs {head['dumb']} dumb "
          f"({head['coordinated'] / max(head['dumb'], 1):.1f}x)")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
