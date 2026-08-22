"""
GridSense optimization engine.

Schedules EV charging sessions against a 24-hour horizon to minimize a
selected objective (marginal emissions, cost, or peak grid load), subject
to each vehicle's energy requirement and deadline, and per-vehicle charger
power limits.

Uses PuLP (CBC solver, bundled) so no external solver install is required.
"""

from dataclasses import dataclass
from typing import Literal

import pulp

from app.tmpdir import ensure_writable_tmpdir

# CBC writes a problem and a solution file per solve. Do this at import, before
# any solver runs, so a full system drive cannot turn into a 500 at request time.
ensure_writable_tmpdir()

Objective = Literal["emissions", "cost", "peak"]

HOURS = list(range(24))


@dataclass
class Vehicle:
    id: str
    energy_needed_kwh: float
    charger_kw: float
    arrival_hour: int
    deadline_hour: int  # hour index (0-23) by which charging must complete, next-day wraparound handled by caller
    # --- vehicle-to-grid ---
    # Discharge rating in kW. 0 means the car can only take charge, which is
    # every scenario in this project until V2G is switched on.
    discharge_kw: float = 0.0
    # Usable pack size, needed once discharging is allowed: without it there is
    # nothing stopping the schedule draining a battery that was never full.
    battery_kwh: float = 60.0
    # Energy in the pack on arrival. The default assumes the car arrives needing
    # exactly what it asks for, which is what the charge-only model implied.
    arrival_soc_kwh: float | None = None
    # Floor the owner will not go below — nobody lends the grid their whole car.
    reserve_kwh: float = 0.0
    # Cap on energy exported across the night. Without one the schedule cycles
    # the pack repeatedly, because the model prices carbon and money but not
    # battery wear, and a free battery is worth cycling until the arbitrage runs
    # out. Real V2G programmes cap throughput for exactly this reason.
    max_export_kwh: float | None = None


@dataclass
class ScenarioResult:
    hourly_naive_load_kw: list
    hourly_optimized_load_kw: list
    hourly_carbon_intensity: list
    peak_naive_kw: float
    peak_optimized_kw: float
    emissions_naive_kg: float
    emissions_optimized_kg: float
    cost_naive: float
    cost_optimized: float
    exported_kwh: float
    peak_reduction_pct: float
    emissions_reduction_pct: float
    cost_reduction_pct: float
    feeder_capacity_kw: float | None
    naive_overload_hours: int
    naive_overload_peak_kw: float


def _available_hours(vehicle: Vehicle) -> list[int]:
    """Hours (0-23) during which this vehicle may charge, honoring wraparound
    deadlines (e.g. arrive at 18:00, must finish by 07:00 next day)."""
    if vehicle.deadline_hour > vehicle.arrival_hour:
        return list(range(vehicle.arrival_hour, vehicle.deadline_hour))
    # wraps past midnight
    return list(range(vehicle.arrival_hour, 24)) + list(range(0, vehicle.deadline_hour))


def max_deliverable_kwh(
    vehicles: list[Vehicle],
    residential_baseline_kw: list[float],
    feeder_capacity_kw: float,
) -> float:
    """Upper bound on energy deliverable under a feeder limit.

    Per hour the fleet can draw at most the headroom the limit leaves after the
    residential baseline, and at most the summed rating of the vehicles plugged
    in that hour. Summing the lesser of the two bounds total energy.

    This is a *necessary* condition only: exceeding it proves infeasibility,
    while satisfying it does not prove feasibility, since individual vehicles'
    windows may still not line up. That is enough to turn "Infeasible" into a
    number the user can act on.
    """
    total = 0.0
    for h in HOURS:
        headroom = feeder_capacity_kw - residential_baseline_kw[h]
        if headroom <= 0:
            continue
        plugged_in = sum(v.charger_kw for v in vehicles if h in set(_available_hours(v)))
        total += min(headroom, plugged_in)
    return total


def naive_schedule(vehicles: list[Vehicle]) -> list[float]:
    """Every vehicle charges at full rated power starting the instant it arrives."""
    load = [0.0] * 24
    for v in vehicles:
        remaining = v.energy_needed_kwh
        for h in _available_hours(v):
            if remaining <= 0:
                break
            draw = min(v.charger_kw, remaining)
            load[h] += draw
            remaining -= draw
    return load


#: Round-trip efficiency of a charge/discharge cycle — inverter losses both
#: ways, roughly 90% for a modern bidirectional charger.
#:
#: The whole loss is charged to the *discharge* leg rather than split across
#: both. Charging stays lossless, which is the convention the rest of this
#: project already uses: `energy_needed_kwh` is grid energy, and every published
#: figure — the 3.3% median saving, the 6.3x hosting capacity — was measured
#: that way. Splitting the loss across both legs would silently move all of them
#: by about 5% while changing nothing about V2G's economics, since only the
#: round trip matters. Exporting a kWh therefore drains ~1.11 kWh from the pack,
#: which has to be imported back before morning.
ROUND_TRIP_EFFICIENCY = 0.90
#: Pack energy consumed per kWh delivered to the grid. A multiplier because PuLP
#: expressions are linear: a variable cannot be divided.
DISCHARGE_DRAIN = 1.0 / ROUND_TRIP_EFFICIENCY


def optimize_schedule(
    vehicles: list[Vehicle],
    carbon_intensity: list[float],  # gCO2/kWh, len 24
    price: list[float] | None = None,  # currency/kWh, len 24
    objective: Objective = "emissions",
    residential_baseline_kw: list[float] | None = None,
    feeder_capacity_kw: float | None = None,
    allow_v2g: bool = False,
) -> list[float]:
    """Solve the LP schedule for the given objective. Returns hourly net EV load
    in kW — negative in an hour where the fleet exports more than it draws.

    With `allow_v2g`, vehicles may discharge back to the grid. That turns the
    problem from "when to buy energy" into "when to buy and when to sell", which
    needs the battery tracked through the night: charge-only scheduling can get
    away with constraining the total, but a schedule that discharges must never
    take a pack below its reserve at any point along the way.
    """
    if price is None:
        price = [1.0] * 24
    if residential_baseline_kw is None:
        residential_baseline_kw = [0.0] * 24

    prob = pulp.LpProblem("gridsense_schedule", pulp.LpMinimize)

    # Charging and discharging are separate non-negative variables rather than
    # one signed variable, because efficiency applies asymmetrically: a signed
    # variable cannot lose 5% in both directions.
    c = {
        (v.id, h): pulp.LpVariable(f"c_{v.id}_{h}", lowBound=0, upBound=v.charger_kw)
        for v in vehicles
        for h in HOURS
    }
    d = {
        (v.id, h): pulp.LpVariable(
            f"d_{v.id}_{h}", lowBound=0,
            upBound=v.discharge_kw if allow_v2g else 0.0,
        )
        for v in vehicles
        for h in HOURS
    }
    # Net draw, which is what the grid and every objective actually sees.
    x = {(v.id, h): c[(v.id, h)] - d[(v.id, h)] for v in vehicles for h in HOURS}

    for v in vehicles:
        window = _available_hours(v)
        avail = set(window)
        for h in HOURS:
            if h not in avail:
                prob += c[(v.id, h)] == 0
                prob += d[(v.id, h)] == 0

        # Energy delivered into the pack, net of losses, must meet the
        # requirement by the deadline.
        # Net energy into the pack by the deadline. Identical to the previous
        # charge-only constraint whenever discharge is zero.
        prob += pulp.lpSum(
            c[(v.id, h)] - d[(v.id, h)] * DISCHARGE_DRAIN for h in HOURS
        ) == v.energy_needed_kwh

        if not allow_v2g:
            continue

        if v.max_export_kwh is not None:
            prob += pulp.lpSum(d[(v.id, h)] for h in HOURS) <= v.max_export_kwh

        # State of charge along the window, in plug-in order rather than clock
        # order — the window wraps midnight, and accumulating by hour index
        # would rewind the battery halfway through the night.
        start = v.arrival_soc_kwh if v.arrival_soc_kwh is not None else v.reserve_kwh
        running = start
        for h in window:
            running = running + c[(v.id, h)] - d[(v.id, h)] * DISCHARGE_DRAIN
            prob += running >= v.reserve_kwh
            prob += running <= v.battery_kwh

    # objective
    if objective == "emissions":
        prob += pulp.lpSum(
            x[(v.id, h)] * carbon_intensity[h] for v in vehicles for h in HOURS
        )
    elif objective == "cost":
        prob += pulp.lpSum(x[(v.id, h)] * price[h] for v in vehicles for h in HOURS)
    else:  # peak
        peak = pulp.LpVariable("peak", lowBound=0)
        for h in HOURS:
            total_h = pulp.lpSum(x[(v.id, h)] for v in vehicles) + residential_baseline_kw[h]
            prob += peak >= total_h
        prob += peak

    # optional feeder capacity constraint
    if feeder_capacity_kw is not None:
        for h in HOURS:
            prob += (
                pulp.lpSum(x[(v.id, h)] for v in vehicles) + residential_baseline_kw[h]
                <= feeder_capacity_kw
            )

    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        needed = sum(v.energy_needed_kwh for v in vehicles)
        if feeder_capacity_kw is not None:
            available = max_deliverable_kwh(vehicles, residential_baseline_kw, feeder_capacity_kw)
            if needed > available:
                raise ValueError(
                    f"A {feeder_capacity_kw:.0f} kW feeder cannot serve this fleet: "
                    f"{needed:.0f} kWh is required by the deadline but at most "
                    f"{available:.0f} kWh fits under the limit once the residential "
                    f"baseline is subtracted. Raise the limit, reduce the fleet, or "
                    f"widen the charging window."
                )
        raise ValueError(f"Optimizer did not find an optimal solution: {pulp.LpStatus[status]}")

    return [sum(x[(v.id, h)].value() for v in vehicles) for h in HOURS]


def run_scenario(
    vehicles: list[Vehicle],
    carbon_intensity: list[float],
    residential_baseline_kw: list[float],
    price: list[float] | None = None,
    objective: Objective = "emissions",
    feeder_capacity_kw: float | None = None,
    schedule_carbon: list[float] | None = None,
    allow_v2g: bool = False,
) -> ScenarioResult:
    """Run a naive-vs-optimized comparison for one night.

    `carbon_intensity` is what actually happened, and is always what the result
    is *scored* against. `schedule_carbon` is what the optimizer was allowed to
    see when choosing hours — pass a day-ahead forecast to measure the schedule
    a real system could have produced. Left unset the two are the same, which is
    perfect foresight and an upper bound rather than an achievable result.
    """
    if price is None:
        price = [1.0] * 24

    naive_ev = naive_schedule(vehicles)
    optimized_ev = optimize_schedule(
        vehicles,
        schedule_carbon if schedule_carbon is not None else carbon_intensity,
        price=price,
        objective=objective,
        residential_baseline_kw=residential_baseline_kw,
        feeder_capacity_kw=feeder_capacity_kw,
        allow_v2g=allow_v2g,
    )

    naive_total = [naive_ev[h] + residential_baseline_kw[h] for h in HOURS]
    optimized_total = [optimized_ev[h] + residential_baseline_kw[h] for h in HOURS]

    peak_naive = max(naive_total)
    peak_optimized = max(optimized_total)

    emissions_naive = sum(naive_ev[h] * carbon_intensity[h] for h in HOURS) / 1000  # kg
    emissions_optimized = sum(optimized_ev[h] * carbon_intensity[h] for h in HOURS) / 1000

    # EV charging cost only — the residential baseline is identical in both
    # scenarios, so including it would dilute the reduction percentage.
    cost_naive = sum(naive_ev[h] * price[h] for h in HOURS)
    cost_optimized = sum(optimized_ev[h] * price[h] for h in HOURS)

    # The naive schedule ignores the feeder limit by construction — that is the
    # point of the comparison. Quantify how badly it breaches, since that is the
    # grid-strain the optimizer is avoiding.
    if feeder_capacity_kw is None:
        overload_hours, overload_peak = 0, 0.0
    else:
        breaches = [naive_total[h] - feeder_capacity_kw for h in HOURS]
        overload_hours = sum(1 for b in breaches if b > 1e-6)
        overload_peak = max(max(breaches), 0.0)

    return ScenarioResult(
        hourly_naive_load_kw=naive_total,
        hourly_optimized_load_kw=optimized_total,
        hourly_carbon_intensity=carbon_intensity,
        peak_naive_kw=peak_naive,
        peak_optimized_kw=peak_optimized,
        emissions_naive_kg=emissions_naive,
        emissions_optimized_kg=emissions_optimized,
        cost_naive=cost_naive,
        cost_optimized=cost_optimized,
        # Energy pushed back to the grid. Hours where the fleet exports show as
        # negative net load, so the sum of those is what left the batteries.
        exported_kwh=round(-sum(min(0.0, v) for v in optimized_ev), 1),
        peak_reduction_pct=round((1 - peak_optimized / peak_naive) * 100, 1) if peak_naive else 0.0,
        emissions_reduction_pct=round((1 - emissions_optimized / emissions_naive) * 100, 1)
        if emissions_naive
        else 0.0,
        cost_reduction_pct=round((1 - cost_optimized / cost_naive) * 100, 1) if cost_naive else 0.0,
        feeder_capacity_kw=feeder_capacity_kw,
        naive_overload_hours=overload_hours,
        naive_overload_peak_kw=round(overload_peak, 2),
    )
