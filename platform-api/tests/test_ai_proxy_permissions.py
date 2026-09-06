"""Tests for the /api/ai/permissions internal callback (TS-ISO-001 fix).

Live finding: this endpoint had no authentication at all -- callers supplied
tenant_id/user_id/project_id as plain query params, and it returned full
project context (datasources, saved SQL, documents with AI summaries, graph
nodes, KPIs) even when the supplied user was not a project member. It is
now POST-only, requires a valid HMAC signature (see
app.services.internal_ai_auth), and denies -- with a constant, minimal body
-- before loading any data when the caller isn't authorized for the project
(owner or active member; a shared project is not automatically tenant-wide).

Run from ``platform-api``: ``pytest -q tests/test_ai_proxy_permissions.py``.
"""

from __future__ import annotations

import time

import pytest

from app.models.project import Project, ProjectMember
from app.models.project_asset import ProjectAsset
from app.services.internal_ai_auth import sign_internal_payload

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants_users as tenants_module
    from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser

    class _FakeSupabase(SupabaseAuthService):
        def __init__(self) -> None:
            pass

        async def create_or_invite_user(
            self, email, *, first_name=None, last_name=None, redirect_to=None
        ) -> SupabaseUser:
            return SupabaseUser(id=f"supa-{email}", email=email, created=True, action_link="x")

    class _FakeEmail:
        async def send_transactional_email(
            self, *, to, template, variables, subject=None, reply_to=None
        ) -> bool:
            return True

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


@pytest.fixture(autouse=True)
def _signing_secret(monkeypatch):
    from types import SimpleNamespace

    import app.routes.ai_proxy_permissions as perms_module

    real_settings = perms_module.get_settings()
    fake_settings = SimpleNamespace(**real_settings.model_dump())
    fake_settings.tablescope_ai_signing_secret = "test-secret"
    monkeypatch.setattr(perms_module, "get_settings", lambda: fake_settings)

    import app.services.internal_ai_auth as auth_module

    monkeypatch.setattr(auth_module, "get_settings", lambda: fake_settings)

    # Replay protection uses Redis; fail-open (as designed) when unavailable
    # in this sandboxed test environment rather than pull in a live Redis.
    async def _no_redis(*a, **k):
        raise ConnectionError("no redis in tests")

    import app.services.home_intel_queue as queue_module

    def _broken_get_redis():
        raise ConnectionError("no redis in tests")

    monkeypatch.setattr(queue_module, "get_redis", _broken_get_redis)


def _signed_body(*, tenant_id: int, user_id: int, project_id: int) -> dict:
    payload = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "project_id": project_id,
        "timestamp": time.time(),
    }
    payload["signature"] = sign_internal_payload(payload, "test-secret")
    return payload


async def _tenant(client, service_headers, slug: str) -> int:
    r = await client.post(
        "/api/tenants", json={"slug": slug, "name": f"{slug} tenant"}, headers=service_headers
    )
    assert r.status_code == 201
    return r.json()["id"]


async def _user(client, service_headers, tenant_id: int, email: str) -> int:
    r = await client.post(
        f"/api/tenants/{tenant_id}/users",
        json={
            "email": email,
            "display_name": "P User",
            "role": "editor",
            "external_id": f"ext-{email}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    return r.json()["id"]


async def test_missing_signature_is_rejected(client, service_headers):
    tenant_id = await _tenant(client, service_headers, "perm-nosig")
    r = await client.post(
        "/api/ai/permissions",
        json={"tenant_id": tenant_id, "user_id": 1, "project_id": 1, "timestamp": time.time()},
    )
    assert r.status_code == 422  # pydantic: signature is a required field


async def test_wrong_signature_is_rejected(client, service_headers):
    tenant_id = await _tenant(client, service_headers, "perm-wrongsig")
    body = _signed_body(tenant_id=tenant_id, user_id=1, project_id=1)
    body["signature"] = "0" * 64
    r = await client.post("/api/ai/permissions", json=body)
    assert r.status_code == 403
    assert r.json() == {"detail": "Forbidden"}


async def test_expired_timestamp_is_rejected(client, service_headers):
    tenant_id = await _tenant(client, service_headers, "perm-stale")
    payload = {
        "tenant_id": tenant_id,
        "user_id": 1,
        "project_id": 1,
        "timestamp": time.time() - 1000,
    }
    payload["signature"] = sign_internal_payload(payload, "test-secret")
    r = await client.post("/api/ai/permissions", json=payload)
    assert r.status_code == 403


async def test_forged_membership_is_denied_with_no_data(
    client, db_session, service_headers
):
    """A signed request for a project the user has no relationship to at
    all must be denied -- and denied WITHOUT leaking whether the project
    exists, is shared, or who owns it (constant minimal body)."""
    tenant_id = await _tenant(client, service_headers, "perm-forged")
    owner_id = await _user(client, service_headers, tenant_id, "owner@perm-forged.com")
    outsider_id = await _user(client, service_headers, tenant_id, "outsider@perm-forged.com")

    project = Project(
        tenant_id=tenant_id, owner_id=owner_id, name="Private Co", is_shared=False
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    body = _signed_body(tenant_id=tenant_id, user_id=outsider_id, project_id=project.id)
    r = await client.post("/api/ai/permissions", json=body)
    assert r.status_code == 403
    assert r.json() == {"detail": "Forbidden"}


async def test_owner_gets_full_context(client, db_session, service_headers):
    tenant_id = await _tenant(client, service_headers, "perm-owner")
    owner_id = await _user(client, service_headers, tenant_id, "owner@perm-owner.com")

    project = Project(
        tenant_id=tenant_id, owner_id=owner_id, name="My Project", is_shared=False
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    body = _signed_body(tenant_id=tenant_id, user_id=owner_id, project_id=project.id)
    r = await client.post("/api/ai/permissions", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["is_owner"] is True
    assert data["is_member"] is True
    assert data["vector_access"] == {
        "version": 1,
        "tenant_id": tenant_id,
        "project_id": project.id,
        "principal_user_id": owner_id,
        "project_access": "owner",
        "project_visibility": "private",
        "can_read_shared_documents": True,
        "private_document_owner_user_id": owner_id,
    }


async def test_permission_context_excludes_other_users_private_documents(
    client, db_session, service_headers
):
    tenant_id = await _tenant(client, service_headers, "perm-private-doc")
    owner_id = await _user(client, service_headers, tenant_id, "owner@private-doc.com")
    member_id = await _user(client, service_headers, tenant_id, "member@private-doc.com")

    project = Project(
        tenant_id=tenant_id, owner_id=owner_id, name="Document Project", is_shared=True
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    db_session.add(
        ProjectMember(project_id=project.id, user_id=member_id, role="viewer", is_active=True)
    )
    db_session.add_all(
        [
            ProjectAsset(
                tenant_id=tenant_id,
                project_id=project.id,
                owner_user_id=owner_id,
                asset_type="document",
                source_type="uploaded_file",
                title="Shared",
                filename="shared.txt",
                storage_location="/tmp/shared.txt",
                visibility="shared_project",
                status="uploaded",
            ),
            ProjectAsset(
                tenant_id=tenant_id,
                project_id=project.id,
                owner_user_id=owner_id,
                asset_type="document",
                source_type="uploaded_file",
                title="Owner private",
                filename="owner-private.txt",
                storage_location="/tmp/owner-private.txt",
                visibility="private",
                status="uploaded",
            ),
            ProjectAsset(
                tenant_id=tenant_id,
                project_id=project.id,
                owner_user_id=member_id,
                asset_type="document",
                source_type="uploaded_file",
                title="Member private",
                filename="member-private.txt",
                storage_location="/tmp/member-private.txt",
                visibility="private",
                status="uploaded",
            ),
        ]
    )
    await db_session.commit()

    r = await client.post(
        "/api/ai/permissions",
        json=_signed_body(tenant_id=tenant_id, user_id=member_id, project_id=project.id),
    )
    assert r.status_code == 200, r.text
    assert {doc["title"] for doc in r.json()["documents"]} == {"Shared", "Member private"}


async def test_shared_project_denies_unrelated_same_tenant_user(
    client, db_session, service_headers
):
    """A shared project is not automatically tenant-wide: is_shared controls
    discoverability/presentation, not authorization on its own (matches the
    isolation assessment's authoritative access policy)."""
    tenant_id = await _tenant(client, service_headers, "perm-shared-outsider")
    owner_id = await _user(client, service_headers, tenant_id, "owner@perm-shared.com")
    outsider_id = await _user(client, service_headers, tenant_id, "outsider@perm-shared.com")

    project = Project(
        tenant_id=tenant_id, owner_id=owner_id, name="Shared Co", is_shared=True
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    body = _signed_body(tenant_id=tenant_id, user_id=outsider_id, project_id=project.id)
    r = await client.post("/api/ai/permissions", json=body)
    assert r.status_code == 403


async def test_shared_project_allows_active_member(client, db_session, service_headers):
    tenant_id = await _tenant(client, service_headers, "perm-shared-member")
    owner_id = await _user(client, service_headers, tenant_id, "owner@perm-member.com")
    member_id = await _user(client, service_headers, tenant_id, "member@perm-member.com")

    project = Project(
        tenant_id=tenant_id, owner_id=owner_id, name="Shared Co", is_shared=True
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    db_session.add(
        ProjectMember(project_id=project.id, user_id=member_id, role="viewer", is_active=True)
    )
    await db_session.commit()

    body = _signed_body(tenant_id=tenant_id, user_id=member_id, project_id=project.id)
    r = await client.post("/api/ai/permissions", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["is_owner"] is False
    assert data["is_member"] is True


async def test_inactive_member_is_denied(client, db_session, service_headers):
    tenant_id = await _tenant(client, service_headers, "perm-inactive")
    owner_id = await _user(client, service_headers, tenant_id, "owner@perm-inactive.com")
    removed_id = await _user(client, service_headers, tenant_id, "removed@perm-inactive.com")

    project = Project(
        tenant_id=tenant_id, owner_id=owner_id, name="Shared Co", is_shared=True
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    db_session.add(
        ProjectMember(project_id=project.id, user_id=removed_id, role="viewer", is_active=False)
    )
    await db_session.commit()

    body = _signed_body(tenant_id=tenant_id, user_id=removed_id, project_id=project.id)
    r = await client.post("/api/ai/permissions", json=body)
    assert r.status_code == 403


async def test_replayed_signature_is_rejected_when_redis_available(
    client, db_session, service_headers, monkeypatch
):
    """When the replay cache IS available, the same signature can't be used
    twice."""
    tenant_id = await _tenant(client, service_headers, "perm-replay")
    owner_id = await _user(client, service_headers, tenant_id, "owner@perm-replay.com")

    project = Project(
        tenant_id=tenant_id, owner_id=owner_id, name="My Project", is_shared=False
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    seen: set[str] = set()

    class _FakeRedis:
        async def set(self, key, value, nx=False, ex=None):
            if nx and key in seen:
                return None
            seen.add(key)
            return True

    import app.services.home_intel_queue as queue_module

    monkeypatch.setattr(queue_module, "get_redis", lambda: _FakeRedis())

    body = _signed_body(tenant_id=tenant_id, user_id=owner_id, project_id=project.id)
    r1 = await client.post("/api/ai/permissions", json=body)
    assert r1.status_code == 200, r1.text

    r2 = await client.post("/api/ai/permissions", json=body)
    assert r2.status_code == 403
