"""Optional run persistence (app/store.py)."""

import pytest
from fastapi.testclient import TestClient

from app import store
from app.main import app

client = TestClient(app)


@pytest.fixture
def db():
    assert store.configure("sqlite://")      # in-memory
    yield
    store.configure("")                       # back to off


def test_runs_endpoint_explains_itself_when_persistence_is_off():
    store.configure("")
    r = client.get("/api/runs")
    assert r.status_code == 501
    assert "DATABASE_URL" in r.json()["detail"]


def test_a_scenario_is_recorded_and_can_be_read_back(db):
    posted = client.post("/api/scenario", json={"ev_count": 12, "objective": "cost"}).json()
    assert posted["run_id"] is not None

    runs = client.get("/api/runs").json()["runs"]
    assert runs[0]["id"] == posted["run_id"]
    assert runs[0]["objective"] == "cost" and runs[0]["ev_count"] == 12
    assert runs[0]["request"]["ev_count"] == 12

    one = client.get(f"/api/runs/{posted['run_id']}").json()
    assert one["cost_reduction_pct"] == posted["cost_reduction_pct"]


def test_newest_first_and_limit(db):
    ids = [client.post("/api/scenario", json={"ev_count": n}).json()["run_id"] for n in (5, 6, 7)]
    runs = client.get("/api/runs?limit=2").json()["runs"]
    assert [r["id"] for r in runs] == [ids[2], ids[1]]


def test_unknown_run_is_404(db):
    assert client.get("/api/runs/99999").status_code == 404


def test_a_run_is_not_recorded_when_the_scenario_is_rejected(db):
    assert client.post("/api/scenario", json={"ev_count": 5000}).status_code == 422
    assert client.get("/api/runs").json()["runs"] == []


def test_a_database_failure_never_breaks_the_scenario(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("database down")

    monkeypatch.setattr(store._engine, "begin", boom)
    r = client.post("/api/scenario", json={"ev_count": 8})
    assert r.status_code == 200 and r.json()["run_id"] is None


def test_unreachable_database_disables_the_store_instead_of_crashing():
    assert store.configure("postgresql://nobody@127.0.0.1:1/none") is False
    assert "could not connect" in store.why_disabled() or "not installed" in store.why_disabled()
    store.configure("")
