"""_widget_configs must honor a forced chart type/subtype/value-scale from
the designer's chart-type picker end to end -- not just at the
_grounded_chart_selection/_apply_chart_overrides layer already covered in
test_ai_dashboard_designer.py. _map_chart_type's older planner vocabulary
maps "heatmap" to a table (a different, unrelated call site's need), so a
forced pick must bypass that mapping rather than go through it.

Run from ``platform-api``:
``pytest -q tests/test_ai_dashboard_designer_widget_configs.py``.
"""

from __future__ import annotations

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models.project import Project
from app.models.saved_query import SavedQuery
from app.models.tenant import Tenant
from app.models.user import User
from app.routes.ai_proxy_dashboard_designer import (
    ChartOverride,
    _apply_chart_overrides,
    _dimension_parameters,
    _widget_configs,
)


def _context(tenant_id: int, user_id: int) -> RequestContext:
    return RequestContext(
        claims=TokenClaims(sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role="editor")
    )


async def _seed(db_session):
    tenant = Tenant(slug="chartpicker", name="ChartPicker")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        tenant_id=tenant.id, email="admin@chartpicker.com", display_name="Admin",
        role="admin", external_id="cp-1",
    )
    db_session.add(user)
    await db_session.flush()

    project = Project(tenant_id=tenant.id, owner_id=user.id, name="Ops", is_shared=False)
    db_session.add(project)
    await db_session.flush()
    await db_session.commit()
    return tenant, user, project


def _combo_widget(title: str) -> dict:
    return {
        "title": title,
        "businessQuestion": "How does revenue compare to backlog?",
        "status": "valid",
        "sql": 'SELECT "Month", "RevenueUSD", "BacklogUSD" FROM t',
        "chartType": "bar_line",
        "labelColumn": "Month",
        "valueColumn": "RevenueUSD",
        "previewData": {
            "columns": ["Month", "RevenueUSD", "BacklogUSD"],
            "rows": [
                {"Month": f"2026-{m:02d}", "RevenueUSD": 100 + m, "BacklogUSD": 50 + m}
                for m in range(1, 13)
            ],
        },
    }


async def test_forced_heatmap_bypasses_the_narrower_planner_type_map(db_session) -> None:
    """_CHART_TYPE_MAP (ai_proxy_widget_helpers.py) maps the planner string
    "heatmap" to a table for an unrelated insight-card call site -- a user
    explicitly picking Heatmap in the designer picker must still get a real
    heatmap widget, not silently downgraded to a table."""
    tenant, user, project = await _seed(db_session)
    context = _context(tenant.id, user.id)

    suggestion = {"widgets": [_combo_widget("Revenue by Month and Region")]}
    _apply_chart_overrides(
        suggestion,
        [ChartOverride(label="Revenue by Month and Region", chart_type="heatmap")],
    )

    configs = await _widget_configs(
        session=db_session, context=context, project_id=project.id,
        suggestion=suggestion, start_index=0,
    )
    assert len(configs) == 1
    assert configs[0]["type"] == "heatmap"


async def test_forced_combo_variant_and_value_scale_reach_the_saved_config(db_session) -> None:
    tenant, user, project = await _seed(db_session)
    context = _context(tenant.id, user.id)

    suggestion = {"widgets": [_combo_widget("Monthly Revenue vs Backlog")]}
    _apply_chart_overrides(
        suggestion,
        [ChartOverride(
            label="Monthly Revenue vs Backlog",
            chart_type="combo", chart_subtype="dual_line", unit="millions",
        )],
    )

    configs = await _widget_configs(
        session=db_session, context=context, project_id=project.id,
        suggestion=suggestion, start_index=0,
    )
    assert len(configs) == 1
    config = configs[0]
    assert config["type"] == "combo"
    assert config["chartSubtype"] == "dual_line"
    assert config["visualizationOptions"]["valueScale"] == "millions"


async def test_dimension_parameters_binds_to_a_real_query_when_picked(db_session) -> None:
    tenant, user, project = await _seed(db_session)
    query = SavedQuery(
        project_id=project.id, owner_id=user.id, name="Sites",
        description="", sql_text='SELECT "Site" FROM sites_CSV',
    )
    db_session.add(query)
    await db_session.commit()
    await db_session.refresh(query)

    params = await _dimension_parameters(
        db_session, project_id=project.id, dimension_label="Site",
        default_period="1_year", query_id=query.id,
    )
    assert params["valueSource"] == "query"
    assert params["queryId"] == query.id
    assert params["dimensionLabel"] == "Site"


async def test_dimension_parameters_falls_back_to_manual_for_an_unknown_or_unset_query(
    db_session,
) -> None:
    tenant, user, project = await _seed(db_session)

    no_pick = await _dimension_parameters(
        db_session, project_id=project.id, dimension_label="Site",
        default_period="1_year", query_id=None,
    )
    assert no_pick["valueSource"] == "manual"
    assert "queryId" not in no_pick

    # A query id from a different project must not bind either.
    other_tenant = Tenant(slug="other", name="Other")
    db_session.add(other_tenant)
    await db_session.flush()
    other_project = Project(tenant_id=other_tenant.id, owner_id=user.id, name="Other", is_shared=False)
    db_session.add(other_project)
    await db_session.flush()
    foreign_query = SavedQuery(
        project_id=other_project.id, owner_id=user.id, name="Foreign",
        description="", sql_text="SELECT 1",
    )
    db_session.add(foreign_query)
    await db_session.commit()
    await db_session.refresh(foreign_query)

    wrong_project = await _dimension_parameters(
        db_session, project_id=project.id, dimension_label="Site",
        default_period="1_year", query_id=foreign_query.id,
    )
    assert wrong_project["valueSource"] == "manual"


async def test_unforced_widget_still_uses_the_grounded_engine_choice(db_session) -> None:
    """No override -> today's behaviour (engine-grounded combo) is unchanged."""
    tenant, user, project = await _seed(db_session)
    context = _context(tenant.id, user.id)

    suggestion = {"widgets": [_combo_widget("Monthly Revenue vs Backlog")]}

    configs = await _widget_configs(
        session=db_session, context=context, project_id=project.id,
        suggestion=suggestion, start_index=0,
    )
    assert len(configs) == 1
    assert configs[0]["type"] == "combo"
    assert configs[0]["chartSubtype"] == "bar_line"
    assert "valueScale" not in configs[0]["visualizationOptions"]
