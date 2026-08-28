"""Tests for the Google Drive OAuth helper (app/services/google_drive/oauth.py)."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.services.google_drive import oauth as gd_oauth

pytestmark = pytest.mark.anyio


def _configured_settings(**overrides):
    base = {
        "google_drive_client_id": "client-123",
        "google_drive_client_secret": "secret-456",
        "google_drive_redirect_uri": "https://app.example.com/oauth/google/callback",
        "google_drive_oauth_scopes": "scope-a scope-b",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_is_configured_requires_all_three_settings(monkeypatch):
    monkeypatch.setattr(gd_oauth, "get_settings", lambda: _configured_settings())
    assert gd_oauth.is_configured() is True

    monkeypatch.setattr(
        gd_oauth, "get_settings", lambda: _configured_settings(google_drive_client_id="")
    )
    assert gd_oauth.is_configured() is False


def test_build_authorization_url_includes_offline_and_consent_prompt(monkeypatch):
    monkeypatch.setattr(gd_oauth, "get_settings", lambda: _configured_settings())
    state = "abc123"
    url = gd_oauth.build_authorization_url(state=state)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert f"state={state}" in url
    assert "client_id=client-123" in url


def test_build_authorization_url_without_config_raises(monkeypatch):
    monkeypatch.setattr(
        gd_oauth, "get_settings", lambda: _configured_settings(google_drive_client_id="")
    )
    with pytest.raises(gd_oauth.GoogleOAuthError):
        gd_oauth.build_authorization_url(state="x")


def test_state_token_round_trips_for_the_issuing_tenant_and_user(monkeypatch):
    token = gd_oauth.create_state_token(tenant_id=7, user_id=42)
    # Does not raise for the same tenant/user.
    gd_oauth.verify_state_token(token, tenant_id=7, user_id=42)


def test_state_token_rejects_a_different_tenant_or_user(monkeypatch):
    token = gd_oauth.create_state_token(tenant_id=7, user_id=42)
    with pytest.raises(gd_oauth.InvalidStateTokenError):
        gd_oauth.verify_state_token(token, tenant_id=7, user_id=99)
    with pytest.raises(gd_oauth.InvalidStateTokenError):
        gd_oauth.verify_state_token(token, tenant_id=1, user_id=42)


def test_state_token_rejects_garbage(monkeypatch):
    with pytest.raises(gd_oauth.InvalidStateTokenError):
        gd_oauth.verify_state_token("not-a-real-token", tenant_id=7, user_id=42)


def test_state_token_rejects_expired_token():
    import json
    from datetime import UTC, datetime

    from app.services.crypto import encrypt_secret

    stale_payload = {
        "tenant_id": 7,
        "user_id": 42,
        "nonce": "n",
        "iat": datetime.now(UTC).timestamp() - gd_oauth._STATE_TOKEN_MAX_AGE_SECONDS - 5,
    }
    token = encrypt_secret(json.dumps(stale_payload))
    with pytest.raises(gd_oauth.InvalidStateTokenError):
        gd_oauth.verify_state_token(token, tenant_id=7, user_id=42)


async def test_exchange_code_for_tokens_requires_refresh_token(monkeypatch):
    monkeypatch.setattr(gd_oauth, "get_settings", lambda: _configured_settings())

    async def fake_post(self, url, **kwargs):
        return httpx.Response(
            200,
            json={"access_token": "at", "expires_in": 3600},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(gd_oauth.GoogleOAuthError, match="refresh token"):
        await gd_oauth.exchange_code_for_tokens(code="one-time-code")


async def test_exchange_code_for_tokens_success_sets_expires_at(monkeypatch):
    monkeypatch.setattr(gd_oauth, "get_settings", lambda: _configured_settings())

    async def fake_post(self, url, **kwargs):
        return httpx.Response(
            200,
            json={
                "access_token": "at",
                "refresh_token": "rt",
                "expires_in": 3600,
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    tokens = await gd_oauth.exchange_code_for_tokens(code="one-time-code")
    assert tokens["access_token"] == "at"
    assert tokens["refresh_token"] == "rt"
    assert "expires_at" in tokens


async def test_exchange_code_for_tokens_rejects_error_response(monkeypatch):
    monkeypatch.setattr(gd_oauth, "get_settings", lambda: _configured_settings())

    async def fake_post(self, url, **kwargs):
        return httpx.Response(400, text="invalid_grant", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(gd_oauth.GoogleOAuthError):
        await gd_oauth.exchange_code_for_tokens(code="bad-code")


async def test_refresh_access_token_keeps_prior_refresh_token_if_none_returned(monkeypatch):
    monkeypatch.setattr(gd_oauth, "get_settings", lambda: _configured_settings())

    async def fake_post(self, url, **kwargs):
        return httpx.Response(
            200,
            json={"access_token": "new-at", "expires_in": 3600},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    tokens = await gd_oauth.refresh_access_token(refresh_token="rt-original")
    assert tokens["access_token"] == "new-at"
    assert tokens["refresh_token"] == "rt-original"
