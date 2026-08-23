"""India's EV fleet and distribution grid, as they actually are.

The rest of this project models 80 identical cars at 7 kW on a 1,250 kW feeder.
That is a European picture. In India it describes almost nothing: 91% of EVs
sold are two- and three-wheelers, and the transformer they charge under is
usually between 63 and 250 kVA.

Fleet shares are FADA retail registrations for calendar 2025:

    two-wheelers    1,279,951   56.4%
    three-wheelers    797,733   35.1%
    passenger cars    176,817    7.8%

Three-wheelers are the striking number — 61% of *all* three-wheeler sales in
India are now electric, so that segment is close to fully electrified rather
than emerging.

Vehicle parameters come from the volume models rather than the flagships:

    e-2W   Ather 450X 2.9-3.7 kWh, 900 W home charger; TVS iQube 650 W
    e-3W   Mahindra Treo 7.4 kWh charging in ~3h50m -> ~1.9 kW
    e-car  Tata Nexon EV class, 3.3 kW single-phase home charging

Nightly energy is what the duty cycle demands, not a full pack. A scooter
commuting 35 km wants under 2 kWh; a shared e-rickshaw worked all day wants
most of its pack back.

Transformer ratings are the IS 1180 standard series. They are apparent power in
kVA, so a power factor is applied to get the real power the feeder can carry —
treating kVA as kW would silently hand every transformer about 10% more
headroom than it has.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "backend"))

from app.optimizer import Vehicle  # noqa: E402

#: FADA calendar-2025 retail registrations, normalised.
FLEET_MIX = {"e2w": 0.564, "e3w": 0.351, "ecar": 0.078}

#: energy wanted overnight (kWh), charger rating (kW), pack size (kWh)
SEGMENTS = {
    "e2w":  {"energy_kwh": 1.8, "charger_kw": 0.90, "battery_kwh": 3.2,
             "label": "Two-wheeler"},
    "e3w":  {"energy_kwh": 6.5, "charger_kw": 1.90, "battery_kwh": 7.4,
             "label": "Three-wheeler"},
    "ecar": {"energy_kwh": 9.2, "charger_kw": 3.30, "battery_kwh": 30.0,
             "label": "Passenger car"},
}

#: IS 1180 standard distribution transformer ratings, kVA.
DT_RATINGS_KVA = [63, 100, 160, 250, 400]

#: Distribution transformers are rated in apparent power. Indian residential
#: feeders with heavy motor and fan load sit near 0.9; EV chargers are close to
#: unity, so this is the conservative end for a mixed feeder.
POWER_FACTOR = 0.90


def dt_ratings_kw() -> list[float]:
    """Standard ratings converted to the real power a feeder can actually carry."""
    return [round(kva * POWER_FACTOR, 1) for kva in DT_RATINGS_KVA]


def indian_fleet(n: int, arrival: int = 18, deadline: int = 7,
                 stagger: bool = True) -> list[Vehicle]:
    """`n` vehicles drawn in the national segment proportions.

    Largest-remainder allocation, so a fleet of 10 is 6/4/1-ish rather than
    silently dropping the car segment to a rounding error.
    """
    exact = {k: n * share for k, share in FLEET_MIX.items()}
    counts = {k: int(v) for k, v in exact.items()}
    for k, _ in sorted(exact.items(), key=lambda kv: kv[1] - int(kv[1]), reverse=True):
        if sum(counts.values()) >= n:
            break
        counts[k] += 1

    # How many hours the window actually holds, and how long the slowest
    # vehicle needs. Staggering a fixed four hours works for a thirteen-hour
    # night and strands a three-wheeler in a six-hour one — it needs 3.4 hours
    # at 1.9 kW, so arriving three hours in leaves it short and the LP reports
    # an infeasible problem rather than a small saving.
    span = (deadline - arrival) % 24 or 24
    slowest = max(s["energy_kwh"] / s["charger_kw"] for s in SEGMENTS.values())
    max_offset = max(0, int(span - slowest))
    spread = min(4, max_offset) if stagger else 1

    fleet: list[Vehicle] = []
    i = 0
    for seg, count in counts.items():
        s = SEGMENTS[seg]
        for j in range(count):
            # Arrivals spread over the early evening. A single instant would make
            # charge-on-arrival look worse than it is, which is the error that
            # inflated the identical-fleet capacity figures elsewhere.
            offset = (j % spread) if spread > 0 else 0
            fleet.append(Vehicle(
                id=f"{seg}-{i}",
                energy_needed_kwh=s["energy_kwh"],
                charger_kw=s["charger_kw"],
                arrival_hour=(arrival + offset) % 24,
                deadline_hour=deadline,
                battery_kwh=s["battery_kwh"],
            ))
            i += 1
    return fleet


def fleet_summary(n: int) -> dict:
    """What `n` Indian EVs actually demand, by segment."""
    fleet = indian_fleet(n)
    out = {}
    for seg in SEGMENTS:
        vs = [v for v in fleet if v.id.startswith(seg)]
        out[seg] = {
            "label": SEGMENTS[seg]["label"],
            "count": len(vs),
            "energy_kwh": round(sum(v.energy_needed_kwh for v in vs), 1),
            "connected_kw": round(sum(v.charger_kw for v in vs), 1),
        }
    out["total"] = {
        "label": "All",
        "count": len(fleet),
        "energy_kwh": round(sum(v.energy_needed_kwh for v in fleet), 1),
        "connected_kw": round(sum(v.charger_kw for v in fleet), 1),
    }
    return out


if __name__ == "__main__":
    print("IS 1180 ratings (kVA -> kW at pf %.2f):" % POWER_FACTOR)
    for kva, kw in zip(DT_RATINGS_KVA, dt_ratings_kw()):
        print(f"  {kva:>4} kVA -> {kw:>6.1f} kW")

    print(f"\n{'segment':<16}{'count':>7}{'energy kWh':>12}{'connected kW':>14}")
    for row in fleet_summary(100).values():
        print(f"{row['label']:<16}{row['count']:>7}{row['energy_kwh']:>12}"
              f"{row['connected_kw']:>14}")

    print("\nThe same 100 vehicles as European cars would want "
          f"{100 * 9.2:.0f} kWh and {100 * 7.0:.0f} kW connected.")
