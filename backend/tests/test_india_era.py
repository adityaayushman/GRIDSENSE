"""India as a first-class simulator scenario."""

from fastapi.testclient import TestClient

from app import data_sources as ds
from app.main import app

client = TestClient(app)
FLEET = [{"count": 57, "energy_per_vehicle_kwh": 1.8, "charger_kw": 0.9, "arrival_hour": 18, "deadline_hour": 7},
         {"count": 35, "energy_per_vehicle_kwh": 6.5, "charger_kw": 1.9, "arrival_hour": 18, "deadline_hour": 7},
         {"count": 8, "energy_per_vehicle_kwh": 9.2, "charger_kw": 3.3, "arrival_hour": 18, "deadline_hour": 7}]


def test_india_era_is_listed_with_its_region_and_stats():
    assert "IN" in ds.eras()
    r = client.get("/api/days?era=IN").json()
    assert r["region"] == "IN" and r["era"] == "IN" and r["count"] > 40
    assert r["year_stats"]["median_saving_pct"] < 1.0          # finding 12: overnight carbon scheduling saves ~nothing


def test_india_scenario_reports_rupees_and_the_indian_region():
    r = client.post("/api/scenario", json={"era": "IN", "fleet": FLEET}).json()
    assert r["currency"] == "INR" and r["region"] == "IN" and r["era"] == "IN"
    assert r["cost_naive"] > 0 and r["forecast_available"] is False


def test_india_uses_its_own_price_and_baseline_not_spains():
    day = ds.default_day("IN")
    price = ds.get_price(day=day, era="IN")
    assert price[0] < price[12] and max(price) < 20             # a rupee curve with a night rebate
    base_in, base_es = ds.get_residential_baseline_kw(100, "IN"), ds.get_residential_baseline_kw(100, "2018")
    assert base_in != base_es and max(base_in) < max(base_es)    # 225 W per home against Spain's level


def test_spanish_eras_still_report_euros():
    assert client.post("/api/scenario", json={}).json()["currency"] == "EUR"


def test_marginal_signal_is_refused_for_india():
    assert client.post("/api/scenario", json={"era": "IN", "signal": "marginal"}).status_code == 422
