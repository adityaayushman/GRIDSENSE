"""Real-data validation of the residential baseline, as served."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_summary_has_one_row_per_region_and_labels_the_evidence():
    s = client.get("/api/validation").json()
    rows = {c["key"]: c for c in s["comparison"]}
    assert set(rows) == {"spain", "uk", "india"}
    assert rows["spain"]["kind"] == rows["uk"]["kind"] == "raw"
    assert rows["india"]["kind"] == "published"          # no open household data: must not pose as raw


def test_every_row_compares_a_model_with_a_real_figure():
    for c in client.get("/api/validation").json()["comparison"]:
        for k in ("model_gain", "real_gain", "model_dumb", "real_dumb", "model_coordinated", "real_coordinated"):
            assert c[k] > 0
        assert c["real_coordinated"] > c["real_dumb"]    # coordination hosts more than charging on arrival


def test_raw_regions_carry_profiles_for_plotting():
    for key in ("spain", "uk"):
        r = client.get(f"/api/validation/{key}").json()
        p = r["baseline"]["profiles"]
        assert len(p["real_winter"]) == len(p["real_annual"]) == len(p["model"]) == 24
        assert r["hosting"]["rows"] and r["homes_in_panel"] > 1000


def test_india_is_a_published_check_with_a_source():
    r = client.get("/api/validation/india").json()
    assert r["kind"] == "published" and r["url"].startswith("https://")
    assert len(r["hosting"]["rows"]) == 4


def test_unknown_region_is_a_404():
    assert client.get("/api/validation/fr").status_code == 404
