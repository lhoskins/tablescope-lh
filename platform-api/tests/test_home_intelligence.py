"""Tests for the Home AI Intelligence suite, preferences, and reports."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.auth.jwt import create_access_token
from app.services import home_intelligence as hi


def _project(pid: int = 1, name: str = "Supply Chain"):
    return SimpleNamespace(id=pid, name=name)


def _table(view: str, columns: list[str]):
    return hi.TableInfo(
        view_name=view, columns=[(c, "string") for c in columns], kind="file"
    )


def _runner(rows_by_fragment: dict[str, list[dict]]):
    async def runner(sql: str) -> dict:
        for fragment, rows in rows_by_fragment.items():
            if fragment in sql:
                cols = list(rows[0].keys()) if rows else []
                return {"columns": cols, "rows": rows}
        return {"columns": [], "rows": []}

    return runner


# ─────────────────────────────── service ────────────────────────────────────

async def test_risk_sla_breach_detected() -> None:
    ctx = hi.ProjectContext(
        tables=[_table("shipments", ["month", "supplier", "lead_time"])],
        documents=[],
    )
    runner = _runner(
        {
            "GROUP BY": [
                {"period": "2024-01", "avg_lead": 12.0},
                {"period": "2024-02", "avg_lead": 22.0},
            ]
        }
    )
    cards = await hi.run_intelligence_suite(_project(), ctx, ["risk_sla"], runner)
    assert len(cards) == 1
    card = cards[0]
    assert card["insightType"] == "risk_sla"
    assert card["severity"] in {"urgent", "critical"}
    assert card["chart"]["type"] == "bar"
    assert "shipments" in card["sources"]["tables"]


async def test_risk_sla_skipped_without_lead_time_column() -> None:
    ctx = hi.ProjectContext(
        tables=[_table("orders", ["id", "name", "qty"])], documents=[]
    )
    cards = await hi.run_intelligence_suite(
        _project(), ctx, ["risk_sla"], _runner({})
    )
    assert cards == []


async def test_risk_expiry_lists_documents_within_90_days() -> None:
    soon = (date.today() + timedelta(days=20)).isoformat()
    far = (date.today() + timedelta(days=400)).isoformat()
    ctx = hi.ProjectContext(
        tables=[],
        documents=[
            hi.DocInfo(
                title="Boeing MSA",
                ai_summary=None,
                ai_metadata={"expiry_date": soon},
            ),
            hi.DocInfo(
                title="Old NDA", ai_summary=None, ai_metadata={"expiry_date": far}
            ),
        ],
    )
    cards = await hi.run_intelligence_suite(
        _project(), ctx, ["risk_expiry"], None
    )
    assert len(cards) == 1
    assert cards[0]["insightType"] == "risk_expiry"
    assert "Boeing MSA" in cards[0]["sources"]["documents"]
    assert "Old NDA" not in cards[0]["sources"]["documents"]
    assert cards[0]["severity"] == "urgent"


async def test_trend_spend_over_budget() -> None:
    ctx = hi.ProjectContext(
        tables=[_table("finance", ["month", "amount", "budget"])], documents=[]
    )
    runner = _runner(
        {
            '"amount"': [{"total": 120000.0}],
            '"budget"': [{"b": 100000.0}],
        }
    )
    cards = await hi.run_intelligence_suite(
        _project(), ctx, ["trend_spend"], runner
    )
    assert len(cards) == 1
    card = cards[0]
    assert card["chart"]["type"] == "kpi_grid"
    assert card["severity"] == "urgent"


async def test_opportunity_supplier_top_performers() -> None:
    ctx = hi.ProjectContext(
        tables=[_table("vendors", ["supplier", "on_time_rate"])], documents=[]
    )
    runner = _runner(
        {
            "GROUP BY": [
                {"supplier": "Acme", "metric": 98.0},
                {"supplier": "Globex", "metric": 91.0},
            ]
        }
    )
    cards = await hi.run_intelligence_suite(
        _project(), ctx, ["opportunity_supplier"], runner
    )
    assert len(cards) == 1
    assert cards[0]["insightType"] == "opportunity_supplier"
    assert cards[0]["callout"]["type"] == "opportunity"


async def test_synthesise_detects_shared_entity() -> None:
    summaries = [
        {
            "projectId": "1",
            "projectName": "Aerospace",
            "insightSummaries": ["Top performer is **Boeing** by far."],
        },
        {
            "projectId": "2",
            "projectName": "Defense",
            "insightSummaries": ["**Boeing** contract expires soon."],
        },
    ]
    result = hi.synthesise_cross_project(summaries)
    assert result is not None
    assert "Boeing" in result["body"]
    assert set(result["projectIds"]) == {"1", "2"}


# ─────────────────────────── endpoints (via client) ─────────────────────────

def _editor_headers(tenant_id: int, user_id: int) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role="editor"
    )
    return {"Authorization": f"Bearer {token}"}


async def _setup(client, service_headers):
    r = await client.post(
        "/api/tenants",
        json={"slug": "hi-tenant", "name": "HI Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "hi@test.com",
            "display_name": "HI User",
            "role": "editor",
            "external_id": "ext-hi",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()
    return tenant, user, _editor_headers(tenant["id"], user["id"])


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants as tenants_module
    from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser

    class _FakeSupabase(SupabaseAuthService):
        def __init__(self) -> None:
            pass

        async def create_or_invite_user(
            self, email, *, first_name=None, last_name=None, redirect_to=None
        ) -> SupabaseUser:
            return SupabaseUser(
                id=f"supa-{email}", email=email, created=True, action_link="x"
            )

    class _FakeEmail:
        async def send(self, spec, *, to, template) -> bool:
            return True

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


async def test_preferences_defaults_and_persist(client, service_headers) -> None:
    _, _, headers = await _setup(client, service_headers)

    r = await client.get("/api/users/preferences", headers=headers)
    assert r.status_code == 200
    prefs = r.json()
    assert prefs["intelligence"]["run_on_load"] is True
    assert prefs["intelligence"]["email_digest"] is False

    r = await client.patch(
        "/api/users/preferences",
        json={"intelligence": {"email_digest": True, "run_on_load": False}},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["intelligence"]["email_digest"] is True

    r = await client.get("/api/users/preferences", headers=headers)
    assert r.json()["intelligence"]["email_digest"] is True
    assert r.json()["intelligence"]["run_on_load"] is False
    # Unspecified default preserved.
    assert r.json()["intelligence"]["cross_project"] is True


async def test_reports_create_get_list_delete(client, service_headers) -> None:
    _, _, headers = await _setup(client, service_headers)

    r = await client.post(
        "/api/reports",
        json={
            "title": "Q1 Risk Review",
            "sections": [{"type": "insight", "insightType": "risk_sla"}],
            "share_settings": {"isPublic": True},
        },
        headers=headers,
    )
    assert r.status_code == 200
    report = r.json()
    token = report["shareToken"]
    assert report["shareUrl"] == f"/reports/{token}"
    assert report["title"] == "Q1 Risk Review"

    r = await client.get(f"/api/reports/{token}", headers=headers)
    assert r.status_code == 200
    assert r.json()["sections"][0]["insightType"] == "risk_sla"

    r = await client.get("/api/reports", headers=headers)
    assert len(r.json()) == 1

    r = await client.delete(f"/api/reports/{token}", headers=headers)
    assert r.status_code == 204

    r = await client.get(f"/api/reports/{token}", headers=headers)
    assert r.status_code == 404


async def test_run_intelligence_suite_no_access(client, service_headers) -> None:
    _, _, headers = await _setup(client, service_headers)
    r = await client.post(
        "/api/ai/run-intelligence-suite",
        json={"project_id": 99999},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["error"] == "no_access"
