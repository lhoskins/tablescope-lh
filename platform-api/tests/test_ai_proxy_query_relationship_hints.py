"""The standalone SQL-generation proxy endpoints (/query/generate and
/actions/generate-and-save-query) must forward evidence-backed join
candidates to the AI server the same way the dashboard proxy endpoints
already do (see test_ai_proxy_shared.py for the underlying discovery
engine, and test_dashboard_multitable_prompt.py for the ai-server side of
this pipeline). Before this, only dashboard widget generation could ever
be told about a real cross-table relationship -- a standalone query asking
to combine two related sources had no way to learn one existed.

Run from ``platform-api``:
``pytest -q tests/test_ai_proxy_query_relationship_hints.py``.
"""

from __future__ import annotations

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.routes import ai_proxy_query, ai_proxy_query_actions
from app.routes.ai_proxy_schemas import (
    AIGenerateAndSaveQueryRequest,
    AIGenerateSQLRequest,
)


def _context(tenant_id: int, user_id: int) -> RequestContext:
    return RequestContext(
        claims=TokenClaims(
            sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role="editor",
        )
    )


async def _seed(db_session):
    tenant = Tenant(slug="relhint", name="RelHint")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        tenant_id=tenant.id,
        email="admin@relhint.com",
        display_name="RelHint Admin",
        role="admin",
        external_id="rh-1",
    )
    db_session.add(user)
    await db_session.flush()

    project = Project(
        tenant_id=tenant.id, owner_id=user.id, name="Sales", is_shared=False,
    )
    db_session.add(project)
    await db_session.flush()

    db_session.add(
        FileSourceMeta(
            tenant_id=tenant.id,
            owner_id=user.id,
            project_id=project.id,
            view_name="sales_revenue_monthly",
            file_name="sales_revenue_monthly.csv",
            column_types=[
                {"name": "month", "type": "string"},
                {"name": "actual_revenue", "type": "decimal"},
            ],
        )
    )
    db_session.add(
        FileSourceMeta(
            tenant_id=tenant.id,
            owner_id=user.id,
            project_id=project.id,
            view_name="sales_bookings_forecast_monthly",
            file_name="sales_bookings_forecast_monthly.csv",
            column_types=[
                {"name": "month", "type": "string"},
                {"name": "forecast_revenue", "type": "decimal"},
            ],
        )
    )
    await db_session.commit()
    return tenant, user, project


async def test_query_generate_forwards_relationship_hints(db_session, monkeypatch):
    tenant, user, project = await _seed(db_session)
    context = _context(tenant.id, user.id)

    captured: dict = {}

    async def fake_forward(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {"sql": 'SELECT "month" FROM "sales_revenue_monthly"'}

    monkeypatch.setattr(ai_proxy_query, "_forward_to_ai", fake_forward)

    await ai_proxy_query.generate_sql(
        AIGenerateSQLRequest(project_id=project.id, prompt="revenue vs forecast by month"),
        session=db_session,
        context=context,
    )

    hints = captured["payload"]["relationship_hints"]
    assert len(hints) == 1
    assert {hints[0]["left_table"], hints[0]["right_table"]} == {
        "sales_revenue_monthly", "sales_bookings_forecast_monthly",
    }


async def test_generate_and_save_query_forwards_relationship_hints_and_rebuilds_group_by(
    db_session, monkeypatch
):
    tenant, user, project = await _seed(db_session)
    context = _context(tenant.id, user.id)

    captured: dict = {}

    async def fake_forward(path, payload):
        captured["payload"] = payload
        # A non-aggregated SELECT column missing from GROUP BY -- the same
        # gap the plain /query/generate endpoint already fixes via
        # rebuild_group_by_from_select before returning.
        return {
            "sql": (
                'SELECT "month", SUM(CAST("actual_revenue" AS double)) AS Revenue '
                'FROM "sales_revenue_monthly" GROUP BY "month", "extra_col"'
            ),
        }

    monkeypatch.setattr(ai_proxy_query_actions, "_forward_to_ai", fake_forward)

    result = await ai_proxy_query_actions.ai_generate_and_save_query(
        AIGenerateAndSaveQueryRequest(
            project_id=project.id, prompt="revenue vs forecast by month",
        ),
        session=db_session,
        context=context,
    )

    hints = captured["payload"]["relationship_hints"]
    assert len(hints) == 1

    assert result["status"] == "saved"
    assert '"extra_col"' not in result["sql_text"]
    assert 'GROUP BY "month"' in result["sql_text"]
