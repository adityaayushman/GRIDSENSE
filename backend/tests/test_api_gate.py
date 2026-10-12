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
