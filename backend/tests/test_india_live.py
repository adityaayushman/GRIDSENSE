"""The keyless Indian live provider (app/india_live.py)."""

import math
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import india_live
from app.india_live import IndiaLiveError, check_plausible, hourly, label_of, parse_rows
from app.main import app

client = TestClient(app)

STAMPS = [f"{(i * 15) // 60}:{(i * 15) % 60:02d}" for i in range(96)]


def solar_curve(i):                       # zero before 06:00 and after 18:00, 60 GW at noon
    h = i / 4
    return max(0.0, 60000 * math.sin(math.pi * (h - 6) / 12)) if 6 <= h <= 18 else 0.0


def day_values(i):
    return {"demand": 200000.0, "nuclear": 6000.0, "wind": 10000.0, "solar": solar_curve(i),
            "hydro": 15000.0, "gas": 3000.0, "thermal": 150000.0, "storage": 1000.0, "others": 2300.0}


def sheet(layout):
    """Rows of a TimeSeries sheet in one of the three layouts Grid-India has used."""
    heads = {
        "2025": ["TIME", "FREQUENCY\n(Hz)", "DEMAND MET\n(MW)", "NUCLEAR\n(MW)", "WIND\n(MW)", "SOLAR\n(MW)", "HYDRO**\n(MW)",
                 "GAS\n(MW)", "THERMAL\n(MW)", "OTHERS*\n(MW)", "NET DEMAND MET\n(MW)", "TOTAL GENERATION\n(MW)"],
        "2026-05": ["TIME", "FREQUENCY", "DEMAND MET¹", "NUCLEAR", "WIND", "SOLAR", "HYDRO²", "GAS", "THERMAL", "STORAGE",
                    "OTHERS³", "NET DEMAND MET", "TOTAL GENERATION"],
        "2026-06": ["TIME", "FREQUENCY", "DEMAND MET¹", "STORAGE DEMAND", "NUCLEAR", "WIND", "SOLAR", "HYDRO²", "GAS",
                    "THERMAL", "STORAGE", "OTHERS³", "NET DEMAND MET", "TOTAL GENERATION"],
    }
    order = {"2025": ["freq", "demand", "nuclear", "wind", "solar", "hydro", "gas", "thermal", "others", "net", "total"],
             "2026-05": ["freq", "demand", "nuclear", "wind", "solar", "hydro", "gas", "thermal", "storage", "others", "net", "total"],
             "2026-06": ["freq", "demand", "storage_demand", "nuclear", "wind", "solar", "hydro", "gas", "thermal", "storage",
                         "others", "net", "total"]}[layout]
    rows = [["Date of Reporting:"], ["15 Min ALL INDIA"], heads[layout], ["", "(A)", "(B)"]]
    for i, stamp in enumerate(STAMPS):
        v = day_values(i)
        v.update(freq=50.0, storage_demand=0.0, net=v["demand"], total=sum(v[k] for k in ("nuclear", "wind", "solar", "hydro", "gas", "thermal", "others")))
        rows.append([stamp] + [v[k] for k in order])
    rows += [["Note: SCADA telemetry"], ["Disclaimer"]]
    return rows


@pytest.mark.parametrize("layout", ["2025", "2026-05", "2026-06"])
def test_every_layout_maps_each_fuel_to_its_own_column(layout):
    """Finding 14: a positional parser read the neighbouring column's fuel for most days."""
    s = parse_rows(sheet(layout))
    assert s["thermal_mw"][0] == 150000.0 and s["gas_mw"][0] == 3000.0
    assert s["wind_mw"][0] == 10000.0 and s["nuclear_mw"][0] == 6000.0 and s["hydro_mw"][0] == 15000.0
    assert max(s["solar_mw"]) > 50000 and s["solar_mw"][0] == 0.0
    assert len(s["demand_met_mw"]) == 96
    assert check_plausible(s)["plausible"]


def test_label_normalisation_ignores_units_footnotes_and_wrapping():
    assert label_of("HYDRO**\n(MW)") == "HYDRO" and label_of("DEMAND MET¹") == "DEMAND MET"
    assert label_of("DEMAND\nMET (MW)") == "DEMAND MET" and label_of("OTHERS³") == "OTHERS"


def test_hourly_intensity_is_a_weighted_mix_and_cleanest_at_midday():
    h = hourly(parse_rows(sheet("2025")))
    ci = h["carbon_intensity"]
    assert len(ci) == 24 and ci.index(min(ci)) == 12
    # coal-dominated overnight: about 150 GW at 820 plus smaller shares, roughly 650-700
    assert 600 < ci[0] < 720 and ci[12] < ci[0]
    assert h["renewable_share_pct"][12] > h["renewable_share_pct"][0]


def test_a_missing_fuel_column_is_rejected_not_filled():
    rows = sheet("2025")
    rows[2] = [("COAL" if "THERMAL" in str(c) else c) for c in rows[2]]
    with pytest.raises(IndiaLiveError, match="missing required columns"):
        parse_rows(rows)


def test_a_short_day_is_rejected():
    rows = sheet("2025")[:-30]
    with pytest.raises(IndiaLiveError, match="96"):
        parse_rows(rows)


def test_solar_at_midnight_fails_the_physical_check():
    s = parse_rows(sheet("2025"))
    s["solar_mw"] = [15000.0] * 96            # the finding-14 symptom: "solar" holding a constant 15 GW
    assert not check_plausible(s)["solar_zero_at_night"]


def test_fuels_that_do_not_sum_to_the_total_fail_closure():
    s = parse_rows(sheet("2025"))
    s["total_generation_mw"] = [v * 1.2 for v in s["total_generation_mw"]]
    c = check_plausible(s)
    assert not c["fuels_sum_to_total"] and not c["plausible"]


def _fake_day(age_days):
    s = parse_rows(sheet("2025"))
    return india_live.IndiaDay(date.today().replace(day=1) if age_days is None else date.fromordinal(date.today().toordinal() - age_days),
                               **hourly(s), checks=check_plausible(s), source_file="x.xls", fetched_at="2026-10-13T00:00:00Z")


def test_endpoint_reports_freshness_and_the_physical_checks(monkeypatch):
    monkeypatch.setattr(india_live, "latest_day", lambda *a, **k: _fake_day(1))
    r = client.get("/api/india/live")
    assert r.status_code == 200
    b = r.json()
    assert b["region"] == "IN" and b["age_days"] == 1 and b["fresh"] is True
    assert len(b["hourly"]) == 24 and b["checks"]["plausible"] is True
    assert b["cleanest_hour"] == 12 and "previous day" in b["note"]


def test_a_stale_report_is_labelled_stale(monkeypatch):
    monkeypatch.setattr(india_live, "latest_day", lambda *a, **k: _fake_day(9))
    b = client.get("/api/india/live").json()
    assert b["fresh"] is False and b["age_days"] == 9


def test_an_unreachable_portal_is_a_502_with_a_reason(monkeypatch):
    def boom(*a, **k):
        raise IndiaLiveError("Grid-India listing unreachable: ConnectError")

    monkeypatch.setattr(india_live, "latest_day", boom)
    r = client.get("/api/india/live")
    assert r.status_code == 502 and "unreachable" in r.json()["detail"]
