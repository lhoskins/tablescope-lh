"""Tests that ai-server signs its outbound call to platform-api's
``/api/ai/permissions`` (TS-ISO-001 fix: platform-api rejects that endpoint
unless the request carries a valid HMAC signature -- see
platform-api/app/services/internal_ai_auth.py and
platform-api/tests/test_ai_proxy_permissions.py for the verifying side).

Run from ``tablescope-ai-api``: ``pytest -q tests/test_context_builder_permissions_call.py``.
"""

from __future__ import annotations

import pytest
import httpx

from app.core.config import settings
from app.core.security import sign_request
from app.services import context_builder

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(settings, "ai_signing_secret", "test-secret")
    monkeypatch.setattr(settings, "tablescope_app_url", "http://platform-api:8000")


async def test_verify_permissions_posts_a_signed_payload(monkeypatch):
    captured: dict = {}

    async def fake_post(self, url, json=None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        return httpx.Response(
            200,
            json={
                "tenant_id": json["tenant_id"],
                "user_id": json["user_id"],
                "project_id": json["project_id"],
                "is_member": True,
                "is_owner": True,
                "project_visibility": "shared",
                "datasources": [],
                "saved_queries": [],
                "dashboards": [],
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await context_builder._verify_permissions(
        tenant_id=1, user_id=2, project_id=3, scope="shared_project"
    )

    assert captured["url"].endswith("/api/ai/permissions")
    body = captured["json"]
    assert body["tenant_id"] == 1
    assert body["user_id"] == 2
    assert body["project_id"] == 3
    assert "signature" in body and "timestamp" in body

    # The signature verifies against the unsigned fields, exactly the shape
    # platform-api's internal_ai_auth reconstructs on the receiving end.
    unsigned = {k: v for k, v in body.items() if k != "signature"}
    assert sign_request(unsigned) == body["signature"]
    assert result["is_member"] is True


async def test_verify_permissions_fails_closed_on_non_200(monkeypatch):
    async def fake_post(self, url, json=None, **kwargs):
        return httpx.Response(403, json={"detail": "Forbidden"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(settings, "require_app_server", True)

    with pytest.raises(context_builder.ContextBuildError):
        await context_builder._verify_permissions(
            tenant_id=1, user_id=2, project_id=3, scope="shared_project"
        )
