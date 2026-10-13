"""The marginal-emissions proxy and the rupee value of avoided upgrades."""

import pytest
from fastapi.testclient import TestClient

from app import marginal, upgrade_value
from app.main import app

client = TestClient(app)


def test_marginal_curve_is_complete_and_bounded():
    c = marginal.curve("ES", "2018-07-04")
    assert len(c) == 24 and all(0 <= v <= 1100 for v in c)


def test_marginal_season_follows_the_month():
    assert marginal.season_of("2018-01-05") == "winter"
    assert marginal.season_of("2018-07-05") == "summer"


def test_marginal_unknown_region_is_a_404():
    assert client.get("/api/marginal?region=FR").status_code == 404


def test_marginal_summary_hides_tables_but_carries_fit_quality():
    g = client.get("/api/marginal").json()["grids"]
    assert {x["grid"] for x in g} == {"Spain", "Germany", "India"}
    assert all("table" not in x and x["median_r2_overnight"] is not None for x in g)


def test_scenario_on_marginal_signal_reports_it_and_scores_in_that_signal():
    r = client.post("/api/scenario", json={"signal": "marginal", "day": "2018-05-15"}).json()
    assert r["signal"] == "marginal" and r["used_forecast"] is False
    assert [h["carbon_intensity"] for h in r["hourly"]] == marginal.curve("ES", "2018-05-15")


def test_marginal_signal_is_refused_outside_its_record():
    r = client.post("/api/scenario", json={"signal": "marginal", "era": "2025"})
    assert r.status_code == 422


def test_average_signal_is_the_default():
    assert client.post("/api/scenario", json={}).json()["signal"] == "average"


def test_prices_rise_with_rating_and_base_sits_between_cases():
    for kva in (63, 100, 160, 250, 400):
        low, base, high = (upgrade_value.equipment_price(kva, c) for c in ("low", "base", "high"))
        assert low < base < high
    assert upgrade_value.equipment_price(100, "low") == pytest.approx(170_000)
    assert upgrade_value.equipment_price(200, "high") == pytest.approx(450_000)
    assert upgrade_value.equipment_price(250, "base") > upgrade_value.equipment_price(100, "base")


def test_same_rating_saves_nothing_and_says_so():
    r = upgrade_value.avoided_upgrade(20)
    assert r["status"] == "same_rating" and r["avoided_inr"]["base"] == 0


def test_crossing_a_rating_boundary_saves_money():
    # 100 kVA hosts 35 on arrival and 123 coordinated; 160 kVA hosts only 91 on arrival.
    r = upgrade_value.avoided_upgrade(100)
    assert (r["rating_on_arrival_kva"], r["rating_coordinated_kva"]) == (250, 100)
    assert r["status"] == "saved"
    assert 0 < r["avoided_inr"]["low"] < r["avoided_inr"]["base"] < r["avoided_inr"]["high"]
    assert r["avoided_per_ev_inr"]["base"] == round(r["avoided_inr"]["base"] / 100)


def test_install_multiplier_scales_the_answer_linearly():
    a = upgrade_value.avoided_upgrade(100, 1.0)["avoided_inr"]["base"]
    b = upgrade_value.avoided_upgrade(100, 2.0)["avoided_inr"]["base"]
    assert b == pytest.approx(2 * a, abs=2)


def test_beyond_the_modelled_range_is_reported_not_priced():
    assert upgrade_value.avoided_upgrade(5000)["status"] == "beyond_range"


def test_endpoint_validates_input():
    assert client.get("/api/upgrade-value?evs=0").status_code == 422
    assert client.get("/api/upgrade-value?evs=100&installed_multiplier=9").status_code == 422
    ok = client.get("/api/upgrade-value?evs=100").json()
    assert ok["status"] == "saved" and ok["currency"] == "INR"
