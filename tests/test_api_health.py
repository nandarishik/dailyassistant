from __future__ import annotations

from fastapi.testclient import TestClient
from src.api.main import app


def test_health_endpoint() -> None:
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_kpi_revenue_total_requires_outlets() -> None:
    client = TestClient(app)
    r = client.get(
        "/v1/kpi/revenue-total",
        params={"date_start": "2026-01-01", "date_end": "2026-01-31"},
    )
    assert r.status_code == 422


def test_morning_brief_job_stub() -> None:
    client = TestClient(app)
    r = client.post("/v1/jobs/morning-brief", json={"dry_run": True})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "not_implemented"
