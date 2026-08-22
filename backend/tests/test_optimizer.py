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


def _greedy(vehicles, carbon):
    """Each vehicle independently fills its own cleanest available hours."""
    from app.optimizer import _available_hours

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


def test_without_a_coupling_constraint_the_lp_only_matches_greedy():
    """Documents why feeder capacity matters.

    With no constraint linking vehicles, the problem separates per vehicle and a
    greedy fill is already optimal — the LP earns nothing. If this ever starts
    failing, some genuine coupling has been introduced and the claim in the
    README needs revisiting.
    """
    carbon = flat_carbon(low_hours={1, 2, 3, 4})
    vehicles = [
        Vehicle(f"v{i}", 6.0 + i % 5, 7.0, 18 + i % 4, 6 + i % 3) for i in range(20)
    ]
    lp = optimize_schedule(vehicles, carbon, objective="emissions")
    greedy = _greedy(vehicles, carbon)
    e_lp = sum(lp[h] * carbon[h] for h in range(24))
    e_greedy = sum(greedy[h] * carbon[h] for h in range(24))
    assert e_lp == pytest.approx(e_greedy, rel=1e-6)


def test_feeder_capacity_is_what_makes_the_lp_necessary():
    """Greedy breaches a shared limit; the LP is what respects it."""
    carbon = flat_carbon(low_hours={2, 3})
    vehicles = [Vehicle(f"v{i}", 9.0, 7.0, 18, 7) for i in range(40)]
    baseline = [5.0] * 24
    cap = 120.0

    greedy = _greedy(vehicles, carbon)
    assert max(g + 5.0 for g in greedy) > cap, "greedy should overrun the limit"

    lp = optimize_schedule(
        vehicles, carbon, residential_baseline_kw=baseline, feeder_capacity_kw=cap
    )
    assert max(lp[h] + baseline[h] for h in range(24)) <= cap + 1e-6
    assert sum(lp) == pytest.approx(sum(v.energy_needed_kwh for v in vehicles), rel=1e-4)


def test_run_scenario_reports_how_far_naive_breaches_the_feeder():
    vehicles = [Vehicle(f"v{i}", 9.2, 7.0, 18, 7) for i in range(80)]
    carbon = flat_carbon(low_hours={2, 3, 4, 5})
    baseline = [2.0] * 24
    result = run_scenario(vehicles, carbon, baseline, objective="emissions",
                          feeder_capacity_kw=400.0)
    assert result.peak_optimized_kw <= 400.0 + 1e-6
    assert result.naive_overload_hours > 0
    assert result.naive_overload_peak_kw > 0
    # Naive is the unconstrained "before" case, so it is expected to breach.
    assert result.peak_naive_kw > 400.0


def test_unconstrained_feeder_reports_no_overload():
    vehicles = [Vehicle("v0", 9.2, 7.0, 18, 7)]
    result = run_scenario(vehicles, flat_carbon(low_hours={3}), [1.0] * 24)
    assert result.feeder_capacity_kw is None
    assert result.naive_overload_hours == 0
    assert result.naive_overload_peak_kw == 0.0


def test_impossible_feeder_explains_itself_with_numbers():
    """A tight limit should yield a planning answer, not a bare 'Infeasible'.

    80 vehicles need 736 kWh across a 13-hour window. With a 2 kW baseline a
    50 kW feeder leaves 48 kW of headroom, so at most 624 kWh can be delivered —
    genuinely impossible. (60 kW would leave 754 kWh and *is* satisfiable, which
    is exactly the sort of near-miss the message is meant to make legible.)
    """
    vehicles = [Vehicle(f"v{i}", 9.2, 7.0, 18, 7) for i in range(80)]
    with pytest.raises(ValueError, match=r"cannot serve this fleet.*kWh is required"):
        optimize_schedule(
            vehicles,
            flat_carbon(low_hours={3}),
            residential_baseline_kw=[2.0] * 24,
            feeder_capacity_kw=50.0,
        )


def test_feasibility_bound_is_a_true_upper_bound():
    """max_deliverable_kwh must never claim less than the LP actually delivers."""
    from app.optimizer import max_deliverable_kwh

    vehicles = [Vehicle(f"v{i}", 9.2, 7.0, 18, 7) for i in range(80)]
    baseline = [2.0] * 24
    for cap in (60.0, 120.0, 300.0, 600.0):
        bound = max_deliverable_kwh(vehicles, baseline, cap)
        load = optimize_schedule(
            vehicles, flat_carbon(low_hours={3}),
            residential_baseline_kw=baseline, feeder_capacity_kw=cap,
        )
        assert sum(load) <= bound + 1e-6, f"bound {bound} under-counts at cap {cap}"


def test_scheduling_on_a_forecast_is_scored_against_actuals():
    """The whole point of the forecast path: the optimizer sees the prediction,
    but the emissions reported are what the real curve would have produced."""
    vehicles = [Vehicle("v0", 7.0, 7.0, 18, 7)]
    actual = flat_carbon(low_hours={3})       # hour 3 is genuinely cleanest
    forecast = flat_carbon(low_hours={5})     # the model wrongly believes hour 5

    result = run_scenario(vehicles, actual, [1.0] * 24, objective="emissions",
                          schedule_carbon=forecast)
    perfect = run_scenario(vehicles, actual, [1.0] * 24, objective="emissions")

    # Charging landed in hour 5, the forecast's pick, not hour 3.
    assert result.hourly_optimized_load_kw[5] > result.hourly_optimized_load_kw[3]
    # And it is scored on the real curve, so it must be worse than perfect foresight.
    assert result.emissions_optimized_kg > perfect.emissions_optimized_kg


def test_omitting_schedule_carbon_is_perfect_foresight():
    vehicles = [Vehicle("v0", 7.0, 7.0, 18, 7)]
    actual = flat_carbon(low_hours={3})
    a = run_scenario(vehicles, actual, [1.0] * 24, objective="emissions")
    b = run_scenario(vehicles, actual, [1.0] * 24, objective="emissions",
                     schedule_carbon=actual)
    assert a.emissions_optimized_kg == pytest.approx(b.emissions_optimized_kg)


def test_a_perfect_forecast_loses_nothing():
    vehicles = [Vehicle(f"v{i}", 9.2, 7.0, 18, 7) for i in range(20)]
    actual = flat_carbon(low_hours={2, 3})
    exact = run_scenario(vehicles, actual, [2.0] * 24, objective="emissions",
                         schedule_carbon=list(actual))
    perfect = run_scenario(vehicles, actual, [2.0] * 24, objective="emissions")
    assert exact.emissions_reduction_pct == pytest.approx(perfect.emissions_reduction_pct)


def test_every_served_night_carries_a_forecast():
    """export_forecast_curves.py must not silently skip nights."""
    for d in data_sources.available_days():
        fc = data_sources.get_carbon_forecast(day=d)
        assert fc is not None, f"{d} has no forecast attached"
        assert len(fc) == 24 and all(v > 0 for v in fc), d


def test_forecast_metadata_names_the_model():
    meta = data_sources.forecast_meta()
    assert meta.get("model"), "forecast provenance missing"
    assert meta["nights_with_forecast"] == len(data_sources.available_days())
