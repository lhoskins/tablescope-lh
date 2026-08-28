"""TS-ISO-007 (platform-api side): the app must refuse to start in
production without a signing secret configured -- an empty secret must
never mean "every ai-server <-> platform-api internal call is unsigned and
accepted," it must mean "the app doesn't start."

Run from ``platform-api``: ``pytest -q tests/test_startup_signing_secret_required.py``.
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


def test_production_without_secret_refuses_to_start(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TABLESCOPE_AI_SIGNING_SECRET", "")
    with pytest.raises(RuntimeError, match="TABLESCOPE_AI_SIGNING_SECRET"):
        create_app()


def test_production_with_secret_starts(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TABLESCOPE_AI_SIGNING_SECRET", "a-real-secret")
    create_app()  # must not raise


def test_development_without_secret_still_starts(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("TABLESCOPE_AI_SIGNING_SECRET", "")
    create_app()  # must not raise -- only production is gated
