"""Health, readiness and metrics contract tests."""

from fastapi.testclient import TestClient

import src.api as api
from src.api import app


def test_liveness_is_independent_of_database(monkeypatch):
    monkeypatch.setattr(api, "check_db", lambda *a, **k: False)
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_readiness_reports_dependencies(monkeypatch):
    monkeypatch.setattr(api, "check_db", lambda *a, **k: True)
    monkeypatch.setattr(api.rag, "is_ready", lambda: True)
    api._ready_cache = (0.0, False, False, False)
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": True, "models": True}


def test_readiness_fails_closed(monkeypatch):
    monkeypatch.setattr(api, "check_db", lambda *a, **k: False)
    monkeypatch.setattr(api.rag, "is_ready", lambda: True)
    api._ready_cache = (0.0, False, False, False)
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_metrics_endpoint_exposes_prometheus_text(monkeypatch):
    monkeypatch.setattr(api, "check_db", lambda *a, **k: True)
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "devsec_http_requests_total" in response.text


def test_request_id_header_and_validation():
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "test-correlation"})
        assert response.headers["X-Request-ID"] == "test-correlation"
        assert "X-Process-Time-Ms" in response.headers

        bad = client.post("/ask", json={"query": "   "})
        assert bad.status_code == 422
