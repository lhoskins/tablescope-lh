"""Tests for Sprint-05 AI governance: analytical-method policy enforcement."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token
from app.services.ai_governance import (
    PolicyVersionConflict,
    ai_governance_service,
    infer_governance_key,
    list_method_definitions,
)
from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _clear_governance_cache():
    """The governance service is a process singleton; clear its cache per test."""
    ai_governance_service.invalidate_cache()


class _FakeSupabase(SupabaseAuthService):
    def __init__(self) -> None:
        pass

    async def create_or_invite_user(
        self, email, *, first_name=None, last_name=None, redirect_to=None
    ) -> SupabaseUser:
        return SupabaseUser(
            id=f"supa-{email}",
            email=email,
            created=True,
            action_link=f"https://invite/{email}",
        )


class _FakeEmail:
    async def send_transactional_email(
        self, *, to, template, variables, subject=None, reply_to=None
    ) -> bool:
        return True


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants_users as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


def _auth_headers(tenant_id: int, user_id: int, role: str = "tenant_admin") -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role=role
    )
    return {"Authorization": f"Bearer {token}"}


async def _setup(client, service_headers, slug: str = "gov-tenant"):
    r = await client.post(
        "/api/tenants",
        json={"slug": slug, "name": f"{slug} tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    tenant = r.json()

    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": f"{slug}@test.com",
            "display_name": "Governance User",
            "role": "admin",
            "external_id": f"ext-{slug}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    user = r.json()
    headers = _auth_headers(tenant["id"], user["id"])
    return tenant, user, headers


# ───────────────────────────── service unit tests ─────────────────────────────


def test_method_registry_is_not_empty():
    methods = list_method_definitions()
    assert any(m.key == "aggregation" for m in methods)
    assert any(m.key == "forecast" for m in methods)


def test_infer_governance_key_question():
    assert infer_governance_key(question="What is the total spend?") == "aggregation"
    assert infer_governance_key(question="Forecast next quarter revenue") == "forecast"
    assert infer_governance_key(question="Are there outliers in delivery time?") == "anomaly_detection"


def test_infer_governance_key_insight_type():
    assert infer_governance_key(insight_type="trend_spend") == "period_over_period_comparison"
    assert infer_governance_key(insight_type="risk_sla") == "rule_based_detection"


async def test_get_effective_policy_returns_defaults(db_session: AsyncSession):
    policy = await ai_governance_service.get_effective_policy(db_session, tenant_id=1)
    assert policy["isDefault"] is True
    assert policy["version"] == 0
    assert policy["methods"]["aggregation"]["enabled"] is True


async def test_update_method_policy_creates_tenant_row(db_session: AsyncSession):
    policy = await ai_governance_service.update_method_policy(
        db_session,
        tenant_id=1,
        user_id=10,
        method_key="forecast",
        enabled=False,
        reason="No forecasting allowed yet.",
        expected_version=0,
    )
    assert policy["isDefault"] is False
    assert policy["version"] == 1
    assert policy["methods"]["forecast"]["enabled"] is False
    assert policy["methods"]["forecast"]["reason"] == "No forecasting allowed yet."

    # Other methods still default to enabled.
    assert policy["methods"]["aggregation"]["enabled"] is True


async def test_update_method_policy_optimistic_lock(db_session: AsyncSession):
    await ai_governance_service.update_method_policy(
        db_session, 1, 10, "forecast", False, None, expected_version=0
    )
    with pytest.raises(PolicyVersionConflict):
        await ai_governance_service.update_method_policy(
            db_session, 1, 10, "forecast", True, None, expected_version=0
        )


async def test_evaluate_method_allows_default(db_session: AsyncSession):
    decision = await ai_governance_service.evaluate_method(
        db_session, 1, "aggregation", project_id=1, insight_id="abc"
    )
    assert decision.allowed is True
    assert decision.effective_method == "aggregation"
    assert decision.fallback_used is False


async def test_evaluate_method_blocks_disabled(db_session: AsyncSession):
    # aggregation does not support a fallback, so disabling it must block.
    await ai_governance_service.update_method_policy(
        db_session, 1, 10, "aggregation", False, "Regulatory hold", expected_version=0
    )
    decision = await ai_governance_service.evaluate_method(
        db_session, 1, "aggregation", project_id=1, insight_id="abc"
    )
    assert decision.allowed is False
    assert decision.fallback_used is False
    assert "disabled" in decision.user_message.lower()


async def test_evaluate_method_uses_fallback(db_session: AsyncSession):
    await ai_governance_service.update_method_policy(
        db_session, 1, 10, "forecast", False, "Not approved", expected_version=0
    )
    decision = await ai_governance_service.evaluate_method(
        db_session, 1, "forecast", project_id=1, insight_id="abc"
    )
    # Fallback to trend_analysis (or period_over_period_comparison) should be active by default.
    assert decision.allowed is True
    assert decision.fallback_used is True
    assert decision.effective_method != "forecast"


async def test_audit_events_are_recorded(db_session: AsyncSession):
    await ai_governance_service.update_method_policy(
        db_session, 1, 10, "forecast", False, "Audit test", expected_version=0
    )
    events = await ai_governance_service.list_audit_events(db_session, tenant_id=1)
    assert events["total"] >= 1
    method_events = [e for e in events["events"] if e["event_type"] == "ai_governance.method_disabled"]
    assert len(method_events) >= 1
    assert method_events[0]["actor_user_id"] == 10


async def test_tenant_isolation(db_session: AsyncSession):
    await ai_governance_service.update_method_policy(
        db_session, 1, 10, "forecast", False, "Tenant 1 only", expected_version=0
    )
    other = await ai_governance_service.get_effective_policy(db_session, tenant_id=2)
    assert other["isDefault"] is True
    assert other["methods"]["forecast"]["enabled"] is True


# ───────────────────────────── route tests ───────────────────────────────────


async def test_get_policy_defaults(client, service_headers):
    _tenant, _user, headers = await _setup(client, service_headers)
    r = await client.get("/api/ai-governance/policy", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_default"] is True
    assert body["methods"]["aggregation"]["enabled"] is True


async def test_update_method_route(client, service_headers):
    _tenant, _user, headers = await _setup(client, service_headers)
    r = await client.patch(
        "/api/ai-governance/methods/forecast",
        json={"enabled": False, "reason": "Route test", "expected_version": 0},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["methods"]["forecast"]["enabled"] is False
    assert body["methods"]["forecast"]["reason"] == "Route test"


async def test_bulk_update_route(client, service_headers):
    _tenant, _user, headers = await _setup(client, service_headers)
    r = await client.put(
        "/api/ai-governance/policy",
        json={
            "methods": [
                {"method_key": "forecast", "enabled": False, "reason": "Bulk"},
                {"method_key": "anomaly_detection", "enabled": True},
            ],
            "expected_version": 0,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["methods"]["forecast"]["enabled"] is False
    assert body["methods"]["anomaly_detection"]["enabled"] is True


async def test_policy_version_conflict_returns_409(client, service_headers):
    _tenant, _user, headers = await _setup(client, service_headers)
    r = await client.patch(
        "/api/ai-governance/methods/forecast",
        json={"enabled": False, "reason": "x", "expected_version": 0},
        headers=headers,
    )
    assert r.status_code == 200
    r = await client.patch(
        "/api/ai-governance/methods/forecast",
        json={"enabled": True, "reason": "x", "expected_version": 0},
        headers=headers,
    )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "policy_version_conflict"


async def test_method_catalog_route(client, service_headers):
    _tenant, _user, headers = await _setup(client, service_headers)
    r = await client.get("/api/ai-governance/method-catalog", headers=headers)
    assert r.status_code == 200, r.text
    methods = r.json()["methods"]
    assert any(m["key"] == "aggregation" for m in methods)


async def test_audit_route_records_policy_change(client, service_headers):
    _tenant, _user, headers = await _setup(client, service_headers)
    r = await client.patch(
        "/api/ai-governance/methods/forecast",
        json={"enabled": False, "reason": "Audit route test", "expected_version": 0},
        headers=headers,
    )
    assert r.status_code == 200
    r = await client.get("/api/ai-governance/audit", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    types = {e["event_type"] for e in body["events"]}
    assert "ai_governance.method_disabled" in types


async def test_non_admin_cannot_update_policy(client, service_headers):
    tenant, user, _admin_headers = await _setup(client, service_headers)
    viewer_headers = _auth_headers(tenant["id"], user["id"], role="viewer")
    r = await client.patch(
        "/api/ai-governance/methods/forecast",
        json={"enabled": False, "reason": "x", "expected_version": 0},
        headers=viewer_headers,
    )
    assert r.status_code == 403


async def test_tenant_isolation_in_routes(client, service_headers):
    _t1, _u1, h1 = await _setup(client, service_headers, "gov-tenant-1")
    _t2, _u2, h2 = await _setup(client, service_headers, "gov-tenant-2")

    await client.patch(
        "/api/ai-governance/methods/forecast",
        json={"enabled": False, "reason": "isolation", "expected_version": 0},
        headers=h1,
    )

    r = await client.get("/api/ai-governance/policy", headers=h2)
    body = r.json()
    assert body["methods"]["forecast"]["enabled"] is True
