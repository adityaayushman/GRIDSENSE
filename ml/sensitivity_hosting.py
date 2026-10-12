"""How far does each assumed input move the hosting-capacity headline?

The 5.3x at 250 kW (FINDINGS.md finding 1) rests on inputs that were chosen, not
measured: the residential baseline *shape*, the fleet's arrival / departure /
energy / charger distributions, and the number of homes on the transformer. The
finding already calls the figure an upper bound; this script puts numbers on
that sentence by moving one input at a time and re-running the headline.

    python sensitivity_hosting.py --list          # show the rows
    python sensitivity_hosting.py --only base     # one row, to time it
    python sensitivity_hosting.py                 # everything (resumable)

This is **sensitivity to assumptions, not validation.** The baseline is system
load, not a metered feeder, so no sweep here shows the true value lies inside
the range found. It also would not have caught the earlier structural errors
(14x from synchronised arrivals, 6.3x from a sevenfold-overstated baseline) —
those were wrong in kind, not in degree.

Ranges, written before the first run, and which are guesses
-----------------------------------------------------------
Every range below is judgement. None is measured, because the data that would
measure them (metered feeders, charging sessions for this fleet) is exactly what
the project does not have.

  peakiness   The base shape swings 0.79-1.12 around its mean (peak/trough 1.4).
              A real residential street swings more. `stretch` multiplies the
              deviation from the mean (0 = flat, 1 = base, 3 = peak/trough ~3.7)
              at constant daily energy. GUESS for 2 and 3: no open feeder data.
              `bump` adds an evening Gaussian (20:00, sd 2h) to the base shape at
              constant daily energy, the specific thing the caveat says is missing.
  fleet mix   arrival: early-heavy / late-heavy; departure: early-heavy (hard
              deadlines, which the finding says would host fewer) / late-heavy;
              energy mean 6 and 14 kWh around the base 9.2; charger mixes
              all-7 kW, slow-heavy, fast-heavy. All GUESSES.
  homes       100 / 150 / 300 / 400 around the base 200, rating fixed at 250 kW.
              GUESS: a 250 kVA unit serving 100-400 dwellings is plausible.
  noise       fleet seeds 1-4 against the base seed 0, nights unchanged. A move
              smaller than this band is not a real effect.

Method matches export_hosting_capacity.py exactly (realistic fleet, 12 sampled
nights, median across nights, dumb found on a step-10 grid, coordinated found by
bisecting the LP) so the `base` row reproduces the published 60 / 318 / 5.3x.
`dumb_fine` re-finds the dumb ceiling on a step-1 grid: with a ceiling near 60,
the step-10 grid alone is a +-17% quantisation on the denominator.

Writes artifacts/sensitivity_hosting.json after every row, so an interrupted run
resumes where it stopped.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import export_hosting_capacity as hc  # noqa: E402  (also puts backend/ on sys.path)
from app import data_sources as ds  # noqa: E402
from app.optimizer import naive_schedule  # noqa: E402

OUT = HERE / "artifacts" / "sensitivity_hosting.json"
RATING = hc.HEADLINE_RATING

BASE = {
    "homes": hc.HOMES,
    "stretch": 1.0,
    "bump": 0.0,
    "arrival": hc.ARRIVAL_MIX,
    "depart": hc.DEPART_MIX,
    "charger": hc.CHARGER_MIX,
    "energy": hc.ENERGY_KWH,
    "seed": 0,
}

# name -> (group, what changed, overrides)
ROWS: dict[str, tuple[str, str, dict]] = {
    "base": ("base", "published headline settings", {}),
    "seed_1": ("noise", "fleet seed 1", {"seed": 1}),
    "seed_2": ("noise", "fleet seed 2", {"seed": 2}),
    "seed_3": ("noise", "fleet seed 3", {"seed": 3}),
    "seed_4": ("noise", "fleet seed 4", {"seed": 4}),
    "stretch_0": ("peakiness", "flat baseline (peak/trough 1.0)", {"stretch": 0.0}),
    "stretch_0.5": ("peakiness", "half the base swing", {"stretch": 0.5}),
    "stretch_2": ("peakiness", "double the base swing", {"stretch": 2.0}),
    "stretch_3": ("peakiness", "triple the base swing (peak/trough ~3.7)", {"stretch": 3.0}),
    "bump_0.5": ("peakiness", "evening bump 0.5 at 20:00", {"bump": 0.5}),
    "bump_1.0": ("peakiness", "evening bump 1.0 at 20:00", {"bump": 1.0}),
    "arrive_early": ("fleet", "arrivals skew early (16-18h)",
                     {"arrival": ([16, 17, 18, 19, 20, 21, 22], [25, 25, 20, 15, 8, 5, 2])}),
    "arrive_late": ("fleet", "arrivals skew late (20-22h)",
                    {"arrival": ([16, 17, 18, 19, 20, 21, 22], [2, 5, 8, 15, 20, 25, 25])}),
    "depart_early": ("fleet", "hard early deadlines (5-6h)",
                     {"depart": ([5, 6, 7, 8, 9], [40, 35, 15, 7, 3])}),
    "depart_late": ("fleet", "relaxed deadlines (8-9h)",
                    {"depart": ([5, 6, 7, 8, 9], [3, 7, 15, 35, 40])}),
    "energy_6": ("fleet", "mean energy 6 kWh", {"energy": 6.0}),
    "energy_14": ("fleet", "mean energy 14 kWh", {"energy": 14.0}),
    "charger_all7": ("fleet", "every charger 7 kW", {"charger": ([3.7, 7.0, 11.0], [0, 100, 0])}),
    "charger_slow": ("fleet", "slow-heavy chargers", {"charger": ([3.7, 7.0, 11.0], [60, 35, 5])}),
    "charger_fast": ("fleet", "fast-heavy chargers", {"charger": ([3.7, 7.0, 11.0], [10, 40, 50])}),
    "homes_100": ("homes", "100 homes", {"homes": 100}),
    "homes_150": ("homes", "150 homes", {"homes": 150}),
    "homes_300": ("homes", "300 homes", {"homes": 300}),
    "homes_400": ("homes", "400 homes", {"homes": 400}),
}


# Five seeds is a thin noise band. Seeds 5-19 widen it to twenty draws; run them
# with `--only` or a plain run, since saved rows are skipped.
for _s in range(5, 20):
    ROWS[f"seed_{_s}"] = ("noise", f"fleet seed {_s}", {"seed": _s})


def baseline(homes: int, stretch: float, bump: float) -> list[float]:
    """The residential baseline with its shape perturbed at constant daily energy."""
    shape = [1.0 + stretch * (s - 1.0) for s in ds.SPAIN_LOAD_SHAPE]
    if bump:
        shape = [s + bump * math.exp(-((h - 20) ** 2) / (2 * 2.0 ** 2)) for h, s in enumerate(shape)]
    scale = ds.SPAIN_DAILY_KWH_PER_HOME / sum(shape)
    return [round(homes * s * scale, 3) for s in shape]


@contextmanager
def patched(cfg: dict):
    """Point the hosting module's globals at this row's inputs, then restore."""
    saved = (hc.ARRIVAL_MIX, hc.DEPART_MIX, hc.CHARGER_MIX, hc.ENERGY_KWH, hc.base_global)
    hc.ARRIVAL_MIX, hc.DEPART_MIX, hc.CHARGER_MIX = cfg["arrival"], cfg["depart"], cfg["charger"]
    hc.ENERGY_KWH = cfg["energy"]
    hc.base_global = baseline(cfg["homes"], cfg["stretch"], cfg["bump"])
    try:
        yield hc.base_global
    finally:
        hc.ARRIVAL_MIX, hc.DEPART_MIX, hc.CHARGER_MIX, hc.ENERGY_KWH, hc.base_global = saved


def dumb_ceiling(builder, base: list[float], step: int) -> int:
    """Largest fleet, on a grid of `step`, whose arrive-and-charge peak fits the rating."""
    best = 0
    for n in range(step, 601, step):
        pk = max(naive_schedule(builder(n))[h] + base[h] for h in range(24))
        if pk <= RATING:
            best = n
        else:
            break
    return best


def coordinated_ceiling(builder, carbon) -> int:
    """Bisect the LP; if the energy-based search bound is reached, widen it and retry."""
    hi = hc.energy_upper_bound(RATING)
    while True:
        try:
            return hc.solver_ceiling(builder, carbon, float(RATING), hi)
        except RuntimeError:
            hi *= 2


def run_row(name: str, nights: int = 12) -> dict:
    group, what, over = ROWS[name]
    cfg = {**BASE, **over}
    t0 = time.time()
    days = ds.available_days()
    sample = days[:: max(1, len(days) // nights)][:nights]
    with patched(cfg) as base:
        builder = lambda n: hc.realistic_fleet(n, cfg["seed"])  # noqa: E731
        dumb = dumb_ceiling(builder, base, 10)
        dumb_fine = dumb_ceiling(builder, base, 1)
        per_night = [coordinated_ceiling(builder, ds.get_carbon_intensity(day=d)) for d in sample]
        residential_peak = max(base)
    coord = int(statistics.median(per_night))
    return {
        "name": name,
        "group": group,
        "what": what,
        "dumb": dumb,
        "dumb_fine": dumb_fine,
        "coordinated": coord,
        "gain": round(coord / max(dumb, 1), 2),
        "gain_fine": round(coord / max(dumb_fine, 1), 2),
        "coordinated_min": min(per_night),
        "coordinated_max": max(per_night),
        "residential_peak_kw": round(residential_peak, 1),
        "seconds": round(time.time() - t0, 1),
    }


def load() -> dict:
    if OUT.exists():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return {"rows": {}}


def save(bundle: dict) -> None:
    bundle.update({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Generated by ml/sensitivity_hosting.py - sensitivity to assumptions, not validation.",
        "rating_kw": RATING,
        "nights": 12,
    })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(bundle, indent=2), encoding="utf-8")


def summary(bundle: dict) -> None:
    rows = bundle["rows"]
    if "base" not in rows:
        return
    b = rows["base"]
    seeds = [rows[k]["gain"] for k in rows if rows[k]["group"] in ("base", "noise")]
    band = (min(seeds), max(seeds))
    print(f"\nbase: dumb {b['dumb']} (fine {b['dumb_fine']}) -> coordinated {b['coordinated']} = {b['gain']}x"
          f" (fine-dumb {b['gain_fine']}x)")
    print(f"noise band over {len(seeds)} seeds: {band[0]}x - {band[1]}x")
    print(f"\n{'row':<14} {'group':<10} {'dumb':>5} {'fine':>5} {'coord':>6} {'gain':>6} {'fine':>6} {'vs base':>8}")
    print("-" * 66)
    for r in rows.values():
        print(f"{r['name']:<14} {r['group']:<10} {r['dumb']:>5} {r['dumb_fine']:>5} {r['coordinated']:>6} "
              f"{r['gain']:>5}x {r['gain_fine']:>5}x {r['gain'] - b['gain']:>+7.2f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", help="comma-separated row names")
    ap.add_argument("--redo", action="store_true", help="recompute rows already saved")
    a = ap.parse_args()
    if a.list:
        for k, (g, w, _) in ROWS.items():
            print(f"{k:<14} {g:<10} {w}")
        return
    names = a.only.split(",") if a.only else list(ROWS)
    bad = [n for n in names if n not in ROWS]
    if bad:
        sys.exit(f"unknown row(s): {bad}")
    bundle = load()
    for n in names:
        if n in bundle["rows"] and not a.redo:
            print(f"  {n}: saved, skipping", flush=True)
            continue
        r = run_row(n)
        bundle["rows"][n] = r
        save(bundle)
        print(f"  {n}: dumb {r['dumb']}/{r['dumb_fine']} coord {r['coordinated']} -> {r['gain']}x "
              f"[{r['seconds']}s]", flush=True)
    summary(bundle)


if __name__ == "__main__":
    main()
