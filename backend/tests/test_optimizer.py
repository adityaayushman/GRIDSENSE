import pytest

from app import data_sources
from app.optimizer import Vehicle, naive_schedule, optimize_schedule, run_scenario


def flat_carbon(low_hours, low_val=100.0, high_val=400.0):
    return [low_val if h in low_hours else high_val for h in range(24)]


def flat_price(low_hours, low_val=0.10, high_val=0.60):
    return [low_val if h in low_hours else high_val for h in range(24)]


def test_naive_schedule_delivers_full_energy():
    v = Vehicle(id="v1", energy_needed_kwh=14.0, charger_kw=7.0, arrival_hour=18, deadline_hour=7)
    load = naive_schedule([v])
    assert sum(load) == pytest.approx(14.0)


def test_naive_schedule_respects_charger_power_limit():
    v = Vehicle(id="v1", energy_needed_kwh=14.0, charger_kw=7.0, arrival_hour=18, deadline_hour=7)
    load = naive_schedule([v])
    assert max(load) <= 7.0 + 1e-6


def test_optimizer_meets_energy_requirement():
    v = Vehicle(id="v1", energy_needed_kwh=10.0, charger_kw=7.0, arrival_hour=18, deadline_hour=7)
    carbon = flat_carbon(low_hours=range(0, 6))
    load = optimize_schedule([v], carbon, objective="emissions")
    assert sum(load) == pytest.approx(10.0, rel=1e-3)


def test_optimizer_shifts_load_to_low_carbon_hours():
    """Given a clear low-carbon window, the optimizer should concentrate
    charging there rather than at arrival time."""
    v = Vehicle(id="v1", energy_needed_kwh=7.0, charger_kw=7.0, arrival_hour=18, deadline_hour=7)
    low_hours = {1, 2, 3}
    carbon = flat_carbon(low_hours=low_hours)
    load = optimize_schedule([v], carbon, objective="emissions")
    load_in_low_hours = sum(load[h] for h in low_hours)
    assert load_in_low_hours == pytest.approx(7.0, rel=1e-3)


def test_optimizer_never_charges_outside_availability_window():
    v = Vehicle(id="v1", energy_needed_kwh=5.0, charger_kw=7.0, arrival_hour=20, deadline_hour=6)
    carbon = flat_carbon(low_hours=[12])  # cheapest hour is outside the window
    load = optimize_schedule([v], carbon, objective="emissions")
    unavailable_hours = set(range(6, 20))
    assert sum(load[h] for h in unavailable_hours) == pytest.approx(0.0, abs=1e-6)


def test_run_scenario_optimized_never_worse_than_naive_on_emissions():
    vehicles = [
        Vehicle(id=f"v{i}", energy_needed_kwh=9.0, charger_kw=7.0, arrival_hour=18, deadline_hour=7)
        for i in range(20)
    ]
    carbon = flat_carbon(low_hours=range(0, 6))
    baseline = [2.0] * 24
    result = run_scenario(vehicles, carbon, baseline, objective="emissions")
    assert result.emissions_optimized_kg <= result.emissions_naive_kg + 1e-6
    assert result.emissions_reduction_pct >= 0


def test_cost_objective_shifts_load_to_cheap_hours():
    v = Vehicle(id="v1", energy_needed_kwh=7.0, charger_kw=7.0, arrival_hour=18, deadline_hour=7)
    cheap = {2, 3}
    load = optimize_schedule(
        [v], flat_carbon(low_hours=[]), price=flat_price(low_hours=cheap), objective="cost"
    )
    assert sum(load[h] for h in cheap) == pytest.approx(7.0, rel=1e-3)


def test_cost_objective_follows_price_not_carbon():
    """Regression guard: `price` must actually reach the LP objective.

    With price and carbon minima placed in different hours, the two objectives
    must produce different schedules. If price is dropped the cost objective
    collapses to a constant (total energy is fixed by constraint) and the solver
    returns an arbitrary feasible schedule.
    """
    v = Vehicle(id="v1", energy_needed_kwh=7.0, charger_kw=7.0, arrival_hour=0, deadline_hour=23)
    carbon = flat_carbon(low_hours={1})
    price = flat_price(low_hours={12})

    cost_load = optimize_schedule([v], carbon, price=price, objective="cost")
    assert cost_load[12] == pytest.approx(7.0, rel=1e-3)

    emissions_load = optimize_schedule([v], carbon, price=price, objective="emissions")
    assert emissions_load[1] == pytest.approx(7.0, rel=1e-3)


def test_run_scenario_threads_price_into_cost_objective():
    """Same bug at the integration level: run_scenario must forward `price`."""
    vehicles = [
        Vehicle(id=f"v{i}", energy_needed_kwh=7.0, charger_kw=7.0, arrival_hour=18, deadline_hour=7)
        for i in range(5)
    ]
    result = run_scenario(
        vehicles,
        flat_carbon(low_hours=[]),
        [2.0] * 24,
        price=flat_price(low_hours={2, 3, 4}),
        objective="cost",
    )
    assert result.cost_optimized < result.cost_naive
    assert result.cost_reduction_pct > 0


def test_price_curve_is_not_flat():
    """A flat tariff would silently turn the cost objective back into a no-op."""
    price = data_sources.get_price()
    assert len(price) == 24
    assert min(price) > 0, "prices include a positive flat access component"
    assert max(price) - min(price) > 1e-4, "real day-ahead prices must vary by hour"


def test_every_stored_day_is_well_formed():
    """Guards the exported artifact: a short or NaN curve would break the LP."""
    days = data_sources.available_days()
    assert len(days) >= 24, f"expected a year-spanning sample of nights, got {len(days)}"
    months = {d[5:7] for d in days}
    assert len(months) == 12, f"sample must span all seasons, got months {sorted(months)}"
    for d in days:
        carbon = data_sources.get_carbon_intensity(day=d)
        price = data_sources.get_price(day=d)
        assert len(carbon) == 24 and len(price) == 24, d
        assert all(c > 0 for c in carbon), d
        assert all(p > 0 for p in price), d


def test_default_day_is_available_and_stable():
    default = data_sources.default_day()
    assert default in data_sources.available_days()
    assert data_sources.resolve_day(None) == default


def test_unknown_day_is_rejected():
    """The endpoint turns this into a 422 rather than serving a silent default."""
    with pytest.raises(ValueError):
        data_sources.resolve_day("1999-01-01")


def test_infeasible_window_raises():
    """A charging window too short to physically deliver the required
    energy at the vehicle's max charger power should be infeasible."""
    v = Vehicle(id="v1", energy_needed_kwh=50.0, charger_kw=7.0, arrival_hour=20, deadline_hour=21)
    carbon = flat_carbon(low_hours=[5])
    with pytest.raises(ValueError):
        optimize_schedule([v], carbon, objective="emissions")
