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

Objective = Literal["emissions", "cost", "peak"]

HOURS = list(range(24))


@dataclass
class Vehicle:
    id: str
    energy_needed_kwh: float
    charger_kw: float
    arrival_hour: int
    deadline_hour: int  # hour index (0-23) by which charging must complete, next-day wraparound handled by caller


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
    peak_reduction_pct: float
    emissions_reduction_pct: float
    cost_reduction_pct: float


def _available_hours(vehicle: Vehicle) -> list[int]:
    """Hours (0-23) during which this vehicle may charge, honoring wraparound
    deadlines (e.g. arrive at 18:00, must finish by 07:00 next day)."""
    if vehicle.deadline_hour > vehicle.arrival_hour:
        return list(range(vehicle.arrival_hour, vehicle.deadline_hour))
    # wraps past midnight
    return list(range(vehicle.arrival_hour, 24)) + list(range(0, vehicle.deadline_hour))


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


def optimize_schedule(
    vehicles: list[Vehicle],
    carbon_intensity: list[float],  # gCO2/kWh, len 24
    price: list[float] | None = None,  # currency/kWh, len 24
    objective: Objective = "emissions",
    residential_baseline_kw: list[float] | None = None,
    feeder_capacity_kw: float | None = None,
) -> list[float]:
    """Solve the LP schedule for the given objective. Returns hourly EV load (kW)."""
    if price is None:
        price = [1.0] * 24
    if residential_baseline_kw is None:
        residential_baseline_kw = [0.0] * 24

    prob = pulp.LpProblem("gridsense_schedule", pulp.LpMinimize)

    # decision vars: power drawn by vehicle v in hour h
    x = {
        (v.id, h): pulp.LpVariable(f"x_{v.id}_{h}", lowBound=0, upBound=v.charger_kw)
        for v in vehicles
        for h in HOURS
    }

    # energy requirement met exactly, only within available hours
    for v in vehicles:
        avail = set(_available_hours(v))
        for h in HOURS:
            if h not in avail:
                prob += x[(v.id, h)] == 0
        prob += pulp.lpSum(x[(v.id, h)] for h in HOURS) == v.energy_needed_kwh

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
        raise ValueError(f"Optimizer did not find an optimal solution: {pulp.LpStatus[status]}")

    return [sum(x[(v.id, h)].value() for v in vehicles) for h in HOURS]


def run_scenario(
    vehicles: list[Vehicle],
    carbon_intensity: list[float],
    residential_baseline_kw: list[float],
    price: list[float] | None = None,
    objective: Objective = "emissions",
    feeder_capacity_kw: float | None = None,
) -> ScenarioResult:
    if price is None:
        price = [1.0] * 24

    naive_ev = naive_schedule(vehicles)
    optimized_ev = optimize_schedule(
        vehicles,
        carbon_intensity,
        price=price,
        objective=objective,
        residential_baseline_kw=residential_baseline_kw,
        feeder_capacity_kw=feeder_capacity_kw,
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
        peak_reduction_pct=round((1 - peak_optimized / peak_naive) * 100, 1) if peak_naive else 0.0,
        emissions_reduction_pct=round((1 - emissions_optimized / emissions_naive) * 100, 1)
        if emissions_naive
        else 0.0,
        cost_reduction_pct=round((1 - cost_optimized / cost_naive) * 100, 1) if cost_naive else 0.0,
    )
