"""ServiceNow ITSM dashboard preset endpoints.

Returns batched KPI cards and chart datasets for the five approved presets.
The feature is gated by the ``servicenow_itsm_dashboards_v2_enabled`` setting.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.tenant import Tenant
from app.routes.dashboards_crud import _require_project_access
from app.services.itsm_metrics import compute_dashboard, list_dashboards
from app.services.itsm_metrics.models import DashboardResult

router = APIRouter(prefix="/projects/{project_id}/itsm-dashboards", tags=["itsm-dashboards"])


class MetricValueOut(BaseModel):
    metricKey: str
    label: str
    value: float | None
    displayValue: str
    periodStart: str
    periodEnd: str
    previousValue: float | None
    delta: float | None
    deltaPercent: float | None
    direction: str | None
    polarity: str
    outcome: str | None
    comparisonLabel: str | None
    status: str
    asOf: str | None


class ChartSeriesOut(BaseModel):
    name: str
    x: list[str]
    y: list[float | None]


class ChartResultOut(BaseModel):
    chartKey: str
    title: str
    chartType: str
    xAxisLabel: str | None = None
    yAxisLabel: str | None = None
    series: list[ChartSeriesOut]
    categories: list[str]


class DashboardResultOut(BaseModel):
    dashboard: str
    asOf: str
    filters: dict[str, Any]
    metrics: list[MetricValueOut]
    charts: list[ChartResultOut]
    dataQuality: dict[str, Any]


def _metric_value_to_dict(mv: Any) -> dict[str, Any]:
    return {
        "metricKey": mv.metric_key,
        "label": mv.label,
        "value": mv.value,
        "displayValue": mv.display_value,
        "periodStart": mv.period_start,
        "periodEnd": mv.period_end,
        "previousValue": mv.previous_value,
        "delta": mv.delta,
        "deltaPercent": mv.delta_percent,
        "direction": mv.direction,
        "polarity": mv.polarity,
        "outcome": mv.outcome,
        "comparisonLabel": mv.comparison_label,
        "status": mv.status,
        "asOf": mv.as_of,
    }


def _chart_to_dict(chart: Any) -> dict[str, Any]:
    return {
        "chartKey": chart.chart_key,
        "title": chart.title,
        "chartType": chart.chart_type,
        "xAxisLabel": chart.x_axis_label,
        "yAxisLabel": chart.y_axis_label,
        "series": [{"name": s.name, "x": s.x, "y": s.y} for s in chart.series],
        "categories": chart.categories,
    }


def _dashboard_to_dict(result: DashboardResult) -> dict[str, Any]:
    return {
        "dashboard": result.dashboard,
        "asOf": result.as_of,
        "filters": result.filters,
        "metrics": [_metric_value_to_dict(m) for m in result.metrics],
        "charts": [_chart_to_dict(c) for c in result.charts],
        "dataQuality": result.data_quality,
    }


async def _itsm_enabled(session: AsyncSession, context: RequestContext) -> bool:
    if get_settings().servicenow_itsm_dashboards_v2_enabled:
        return True
    tenant = await session.get(Tenant, context.tenant_id)
    return bool(tenant and tenant.servicenow_itsm_dashboards_v2_enabled)


@router.get("")
async def list_itsm_dashboard_presets(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[str]:
    """List available ITSM dashboard presets."""
    await _require_project_access(project_id, session, context)
    if not await _itsm_enabled(session, context):
        raise HTTPException(status_code=404, detail="ITSM dashboards are not enabled")
    return list_dashboards()


@router.get("/{preset}")
async def get_itsm_dashboard(
    project_id: int,
    preset: str,
    site: str | None = Query(default=None),
    as_of: datetime | None = Query(default=None, alias="asOf"),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> DashboardResultOut:
    """Return KPI cards and chart data for a single ITSM dashboard preset."""
    await _require_project_access(project_id, session, context)
    if not await _itsm_enabled(session, context):
        raise HTTPException(status_code=404, detail="ITSM dashboards are not enabled")

    try:
        result = await compute_dashboard(
            dashboard_key=preset,
            project_id=project_id,
            session=session,
            tenant_id=context.tenant_id,
            as_of=as_of,
            site_code=site,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Dashboard computation failed: {exc}") from exc

    return DashboardResultOut(**_dashboard_to_dict(result))
