"""Tests for TS-ISO-018: CORS wildcard-with-credentials and anonymous
/metrics.

Run from ``platform-api``: ``pytest -q tests/test_cors_and_metrics_hardening.py``.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_production_with_wildcard_cors_refuses_to_start(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TABLESCOPE_AI_SIGNING_SECRET", "a-real-secret")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="CORS_ALLOW_ORIGINS"):
        create_app()


def test_production_with_empty_cors_refuses_to_start(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TABLESCOPE_AI_SIGNING_SECRET", "a-real-secret")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "")
    with pytest.raises(RuntimeError, match="CORS_ALLOW_ORIGINS"):
        create_app()


def test_production_with_explicit_origins_starts(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TABLESCOPE_AI_SIGNING_SECRET", "a-real-secret")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://app.tablescope.cloud")
    create_app()  # must not raise


def test_development_with_wildcard_cors_still_starts(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")
    create_app()  # must not raise -- only production is gated


def _metrics_test_client(monkeypatch, *, access_token: str = ""):
    """/metrics is disabled in the shared test app (PROMETHEUS_ENABLED=false
    in conftest, since prometheus_client's global REGISTRY can't be reset
    per-app) -- build a small standalone app with it explicitly mounted to
    test the route itself."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.observability import mount_metrics

    settings = get_settings()
    monkeypatch.setattr(settings, "prometheus_enabled", True)
    monkeypatch.setattr(settings, "metrics_access_token", access_token)
    app = FastAPI()
    mount_metrics(app)
    return TestClient(app)


def test_metrics_open_when_no_token_configured(monkeypatch):
    client = _metrics_test_client(monkeypatch, access_token="")
    r = client.get("/metrics")
    assert r.status_code == 200


def test_metrics_requires_token_when_configured(monkeypatch):
    client = _metrics_test_client(monkeypatch, access_token="scrape-secret")
    r = client.get("/metrics")
    assert r.status_code == 404

    r = client.get("/metrics", headers={"X-Metrics-Token": "wrong"})
    assert r.status_code == 404

    r = client.get("/metrics", headers={"X-Metrics-Token": "scrape-secret"})
    assert r.status_code == 200


def test_metrics_labels_use_route_template_not_raw_path(monkeypatch):
    """A request to a parameterized route must not leak the concrete ID
    into the exported metric's path label (or blow up cardinality)."""
    client = _metrics_test_client(monkeypatch, access_token="")
    client.app.get("/items/{item_id}")(lambda item_id: {"id": item_id})

    client.get("/items/12345")
    body = client.get("/metrics").text
    assert "/items/12345" not in body
    assert "/items/{item_id}" in body
