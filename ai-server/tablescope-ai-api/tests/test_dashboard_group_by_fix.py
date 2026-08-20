"""Dashboard-suggest widget SQL must get the same missing-GROUP-BY repair
/ai/intelligence/plan's analyses already get.

Live regression on project 41: the model's cross-table combo widget selected
a non-aggregate `COALESCE(b."BacklogUSD", 0) AS BacklogUSD` alongside the
aggregate revenue column, but only grouped by the join key --
`GROUP BY COALESCE(r."Month", b."Month")`. Teiid rejected it with TEIID30492
("[b.BacklogUSD] cannot be used outside of aggregate functions since they
are not present in a GROUP BY clause"), so the widget returned 0 rows.
_ensure_group_by (ai_plan_sql.py) already exists to fix exactly this shape
for /ai/intelligence/plan's analyses -- it was never wired into the
dashboard-suggest endpoints' widget SQL post-processing.

Run from ``tablescope-ai-api``: ``pytest -q tests/test_dashboard_group_by_fix.py``.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import app.routers.ai_dashboard as ai_dashboard
from app.models.schemas import SuggestDashboardRequest, SuggestDashboardsMultiRequest

_MISSING_GROUP_BY_SQL = (
    'SELECT COALESCE(r."Month", b."Month") AS Month, '
    'SUM(CAST(r."RevenueUSD" AS double)) AS RevenueUSD, '
    'COALESCE(b."BacklogUSD", 0) AS BacklogUSD '
    'FROM sales_revenue_monthly_CSV r FULL OUTER JOIN sales_backlog_monthly_CSV b '
    'ON r."Month" = b."Month" '
    'GROUP BY COALESCE(r."Month", b."Month") '
    "ORDER BY Month DESC LIMIT 12"
)


@pytest.fixture(autouse=True)
def _patch_endpoint(monkeypatch):
    monkeypatch.setattr(ai_dashboard, "verify_signature", lambda *a, **k: None)

    async def fake_build_context(**kwargs):
        class _Ctx:
            allowed_context = {"metadata": []}

        return _Ctx()

    monkeypatch.setattr(ai_dashboard.context_builder, "build_context", fake_build_context)
    monkeypatch.setattr(ai_dashboard.context_builder, "context_to_prompt_text", lambda ctx: "")
    monkeypatch.setattr(ai_dashboard, "update_activity", lambda *a, **k: None)
    monkeypatch.setattr(ai_dashboard, "load_prompt_reference", lambda *a, **k: "")
    monkeypatch.setattr(ai_dashboard, "format_knowledge_graph_context", lambda *a, **k: "")


def _fake_generate(response: str):
    async def _generate(**kwargs):
        return response

    return _generate


def test_suggest_dashboard_repairs_a_widget_missing_a_group_by_column(monkeypatch):
    response = json.dumps({
        "title": "t", "description": "d", "business_domain": "sales",
        "intended_audience": "executive", "executive_summary": "s",
        "widgets": [{
            "type": "dual_line", "title": "Revenue vs Backlog by Month",
            "sql": _MISSING_GROUP_BY_SQL,
            "label_column": "Month", "value_column": "RevenueUSD",
        }],
    })
    monkeypatch.setattr(ai_dashboard.llm_client, "generate", _fake_generate(response))
    req = SuggestDashboardRequest(
        tenant_id=1, user_id=1, project_id=1,
        allowed_tables=["sales_revenue_monthly_CSV", "sales_backlog_monthly_CSV"],
    )

    resp = asyncio.run(ai_dashboard.suggest_dashboard(req))

    sql = resp.suggestions[0].widgets[0].sql
    assert 'GROUP BY COALESCE(r."Month", b."Month"), COALESCE(b."BacklogUSD", 0)' in sql


def test_suggest_dashboards_multi_repairs_a_widget_missing_a_group_by_column(monkeypatch):
    response = json.dumps({
        "suggestions": [{
            "title": "t", "description": "d", "business_purpose": "p",
            "audience": "executive",
            "widgets": [{
                "title": "Revenue vs Backlog by Month", "chart_type": "dual_line",
                "business_question": "", "sql": _MISSING_GROUP_BY_SQL,
                "label_column": "Month", "value_column": "RevenueUSD",
            }],
            "kpis": [], "data_sources": ["sales_revenue_monthly_CSV", "sales_backlog_monthly_CSV"],
            "confidence": 0.8, "quality_score": 90,
        }],
    })
    monkeypatch.setattr(ai_dashboard.llm_client, "generate", _fake_generate(response))
    req = SuggestDashboardsMultiRequest(
        tenant_id=1, user_id=1, project_id=1,
        allowed_tables=["sales_revenue_monthly_CSV", "sales_backlog_monthly_CSV"],
    )

    resp = asyncio.run(ai_dashboard.suggest_dashboards_multi(req))

    sql = resp.suggestions[0].widgets[0].sql
    assert 'GROUP BY COALESCE(r."Month", b."Month"), COALESCE(b."BacklogUSD", 0)' in sql
