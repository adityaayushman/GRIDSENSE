"""The two grid eras: the original 2018 record and Spain as it is now (2025)."""

import pytest
from fastapi.testclient import TestClient

from app import data_sources
from app.main import app

client = TestClient(app)


def test_both_eras_are_available_and_2018_is_the_default():
    assert data_sources.eras() == ["2018", "2025", "IN"]
    d = client.get("/api/days").json()
    assert d["era"] == "2018" and d["count"] == 46
    assert d["default"] in d["days"] and d["default"].startswith("2018-")


def test_days_endpoint_serves_the_2025_nights_with_whole_year_statistics():
    d = client.get("/api/days?era=2025").json()
    assert d["era"] == "2025" and d["count"] > 40
    assert all(day.startswith("2025-") for day in d["days"]) or all(day.startswith(("2025-", "2026-")) for day in d["days"])
    s = d["year_stats"]
    assert s["year"] == 2025 and s["nights"] > 300
    assert 0 <= s["under_1pct"] <= 100 and s["total_saving_pct"] > s["median_saving_pct"]


def test_2018_whole_year_statistics_come_from_the_served_file_not_from_the_source():
    s = client.get("/api/days?era=2018").json()["year_stats"]
    assert s["year"] == 2018 and s["nights"] > 300
    assert 0 < s["median_saving_pct"] < s["total_saving_pct"] < 20
    assert s == data_sources.year_stats("2018")


def test_unknown_era_is_rejected():
    assert client.get("/api/days?era=1999").status_code == 404
    assert client.post("/api/scenario", json={"era": "1999"}).status_code == 422


def test_a_2025_scenario_runs_against_2025_data_and_says_so():
    day = client.get("/api/days?era=2025").json()["default"]
    r = client.post("/api/scenario", json={"era": "2025", "day": day, "ev_count": 20, "use_forecast": True})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["era"] == "2025" and b["day"] == day and b["used_forecast"] is True
    assert len(b["hourly_forecast"]) == 24


def test_a_2018_night_is_not_valid_in_2025():
    r = client.post("/api/scenario", json={"era": "2025", "day": "2018-07-31"})
    assert r.status_code == 422 and "2025" in r.json()["detail"]


def test_the_modern_grid_is_cleaner_than_the_old_one():
    old = data_sources.get_carbon_intensity(day=data_sources.default_day("2018"), era="2018")
    new = data_sources.get_carbon_intensity(day=data_sources.default_day("2025"), era="2025")
    nights = lambda era: [sum(data_sources.get_carbon_intensity(day=d, era=era)) / 24 for d in data_sources.available_days(era)]
    assert sum(nights("2025")) / len(nights("2025")) < sum(nights("2018")) / len(nights("2018"))
    assert len(old) == len(new) == 24


def test_every_2025_night_has_complete_curves():
    for d in data_sources.available_days("2025"):
        assert len(data_sources.get_carbon_intensity(day=d, era="2025")) == 24
        assert len(data_sources.get_price(day=d, era="2025")) == 24
        f = data_sources.get_carbon_forecast(day=d, era="2025")
        assert f is not None and len(f) == 24
