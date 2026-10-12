"""The forecast gate through the HTTP API (FINDINGS.md finding 13)."""

import pytest
from fastapi.testclient import TestClient

from app import data_sources
from app.main import app

client = TestClient(app)


def _post(**body):
    return client.post("/api/scenario", json={"ev_count": 20, **body})


def _night_with_forecast():
    return next(d for d in data_sources.available_days() if data_sources.get_carbon_forecast("ES", d))


def test_response_reports_the_gate_as_off_when_not_requested():
    r = _post(day=_night_with_forecast(), use_forecast=True).json()
    assert r["gate_applied"] is False and r["gate_reason"] is None


def test_gate_with_forecast_reports_expected_saving_and_decision():
    r = _post(day=_night_with_forecast(), use_forecast=True, gate_min_saving_pct=7.5).json()
    assert r["gate_applied"] is True
    assert r["gate_expected_saving_pct"] is not None
    # acting or stepping aside, the decision must be consistent with the threshold
    assert r["gate_acted"] == (r["gate_expected_saving_pct"] >= 7.5)


def test_an_unreachable_threshold_always_charges_on_arrival():
    r = _post(day=_night_with_forecast(), use_forecast=True, gate_min_saving_pct=50.0).json()
    assert r["gate_acted"] is False
    assert r["emissions_reduction_pct"] == 0.0


def test_gate_without_use_forecast_is_ignored_with_a_reason():
    r = _post(use_forecast=False, gate_min_saving_pct=7.5).json()
    assert r["gate_applied"] is False
    assert "forecast" in r["gate_reason"]


def test_gate_is_ignored_under_a_feeder_limit():
    r = _post(day=_night_with_forecast(), use_forecast=True, gate_min_saving_pct=7.5,
              feeder_capacity_kw=400).json()
    assert r["gate_applied"] is False
    assert "feeder" in r["gate_reason"]


def test_threshold_is_validated():
    assert _post(gate_min_saving_pct=-1).status_code == 422
    assert _post(gate_min_saving_pct=80).status_code == 422


# --- mixed fleets -----------------------------------------------------------

def test_mixed_fleet_schedules_every_group_and_reports_the_totals():
    fleet = [
        {"count": 30, "energy_per_vehicle_kwh": 2.0, "charger_kw": 0.9},      # scooters
        {"count": 10, "energy_per_vehicle_kwh": 7.0, "charger_kw": 1.9},      # rickshaws
        {"count": 5, "energy_per_vehicle_kwh": 20.0, "charger_kw": 7.0},      # cars
    ]
    r = client.post("/api/scenario", json={"fleet": fleet})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ev_count"] == 45
    assert body["energy_scheduled_kwh"] == pytest.approx(30 * 2 + 10 * 7 + 5 * 20)
    delivered = sum(h["optimized_kw"] for h in body["hourly"])   # baseline-free check below
    assert delivered > 0


def test_fleet_replaces_the_single_group_fields():
    one = client.post("/api/scenario", json={"ev_count": 80}).json()
    mixed = client.post("/api/scenario", json={
        "ev_count": 80, "fleet": [{"count": 3, "energy_per_vehicle_kwh": 5.0, "charger_kw": 3.0}],
    }).json()
    assert mixed["ev_count"] == 3 and one["ev_count"] == 80


def test_fleet_over_the_vehicle_limit_is_rejected():
    big = [{"count": 600, "energy_per_vehicle_kwh": 5.0, "charger_kw": 3.0}] * 2
    assert client.post("/api/scenario", json={"fleet": big}).status_code == 422


def test_a_group_that_cannot_charge_in_its_window_is_a_clear_error():
    # 40 kWh through a 1 kW charger in a one-hour window is physically impossible.
    r = client.post("/api/scenario", json={"fleet": [
        {"count": 2, "energy_per_vehicle_kwh": 40.0, "charger_kw": 1.0, "arrival_hour": 18, "deadline_hour": 19},
    ]})
    assert r.status_code == 422
