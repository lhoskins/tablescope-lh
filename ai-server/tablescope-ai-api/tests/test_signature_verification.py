"""Tests for app/core/security.py's HMAC request signing/verification.

Live security fix (TS-ISO-007): verify_signature used to silently SKIP
verification whenever AI_SIGNING_SECRET was empty ("dev mode"), which meant
an operator forgetting to set the secret in production turned every
request -- signed or not -- into an accepted one. It now fails closed.

Run from ``tablescope-ai-api``: ``pytest -q tests/test_signature_verification.py``.
"""

from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

from app.core import security
from app.core.config import settings


@pytest.fixture(autouse=True)
def _restore_secret():
    original = settings.ai_signing_secret
    yield
    settings.ai_signing_secret = original


def test_empty_secret_rejects_instead_of_skipping():
    settings.ai_signing_secret = ""
    payload = {"tenant_id": 1, "timestamp": time.time()}
    with pytest.raises(HTTPException) as exc:
        security.verify_signature(payload, "any-signature")
    assert exc.value.status_code == 403


def test_valid_signature_with_configured_secret_passes():
    settings.ai_signing_secret = "test-secret"
    payload = {"tenant_id": 1, "timestamp": time.time()}
    signature = security.sign_request(payload)
    security.verify_signature(payload, signature)  # must not raise


def test_wrong_signature_is_rejected():
    settings.ai_signing_secret = "test-secret"
    payload = {"tenant_id": 1, "timestamp": time.time()}
    with pytest.raises(HTTPException) as exc:
        security.verify_signature(payload, "wrong-signature")
    assert exc.value.status_code == 403


def test_stale_timestamp_is_rejected():
    settings.ai_signing_secret = "test-secret"
    payload = {"tenant_id": 1, "timestamp": time.time() - security.SIGNATURE_MAX_AGE_SECONDS - 5}
    signature = security.sign_request(payload)
    with pytest.raises(HTTPException) as exc:
        security.verify_signature(payload, signature)
    assert exc.value.status_code == 403
    assert "expired" in exc.value.detail
