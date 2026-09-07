"""TS-ISO-020: TABLESCOPE_SECRET_KEY must fail closed in production.

Mirrors the existing TABLESCOPE_AI_SIGNING_SECRET / CORS_ALLOW_ORIGINS
fail-closed startup guards in ``app.main.create_app`` -- an empty secret
key must never silently fall back to a key derived from JWT_SECRET_KEY
when running in production.
"""

from __future__ import annotations

import pytest

from app import main as main_module
from app.config import Settings


def _production_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "ENVIRONMENT": "production",
        "tablescope_ai_signing_secret": "test-signing-secret",
        "cors_allow_origins": "https://app.example.com",
        "tablescope_secret_key": "test-fernet-key",
    }
    defaults.update(overrides)
    # Pydantic Settings uses ENVIRONMENT as the validation alias for the
    # environment field, so make sure kwarg-based overrides use it.
    if "environment" in defaults:
        defaults["ENVIRONMENT"] = defaults.pop("environment")
    return Settings(**defaults)


def test_missing_secret_key_refuses_to_start_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _production_settings(tablescope_secret_key="")
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match="TABLESCOPE_SECRET_KEY must be set"):
        main_module.create_app()


def test_configured_secret_key_starts_normally_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _production_settings()
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    app = main_module.create_app()

    assert app is not None


def test_missing_secret_key_is_allowed_outside_production(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _production_settings(environment="development", tablescope_secret_key="")
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    app = main_module.create_app()

    assert app is not None
