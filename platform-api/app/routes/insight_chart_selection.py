"""Chart Suggestion modal persistence route.

Allows a user to change the chart family for an insight card. The selected
visualization is written back into every cached snapshot that contains the
card so the choice survives refresh, Home pins, and dashboard add.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.routes.home_pins import _require_project_access
from app.services.insight_chart_selection import persist_chart_selection

router = APIRouter(prefix="/ai/insights", tags=["AI Intelligence"])


class ChartSelectionRequest(BaseModel):
    project_id: int = Field(..., ge=1)
    selection: dict[str, Any] = Field(default_factory=dict)


class ChartSelectionResponse(BaseModel):
    updated: bool
    insight_id: str


@router.post("/{insight_id}/chart-selection")
async def apply_chart_selection(
    insight_id: str,
    body: ChartSelectionRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ChartSelectionResponse:
    """Persist the user's chart selection for an insight card."""
    await _require_project_access(session, context, body.project_id)

    selection = body.selection or {}
    # Security: reject raw ECharts option objects; only allow registered chart
    # family keys and a bounded set of options surfaced by the modal.
    allowed_chart_keys = {
        "chartType",
        "chartSubtype",
        "visualizationDecision",
        "xField",
        "yField",
        "y2Field",
        "valueFormat",
    }
    if not set(selection.keys()).issubset(allowed_chart_keys):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selection contains unsupported chart options",
        )
    if selection.get("visualizationDecision") and not isinstance(
        selection.get("visualizationDecision"), dict
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="visualizationDecision must be an object",
        )

    updated = await persist_chart_selection(
        session,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=body.project_id,
        insight_id=insight_id,
        selection=selection,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Insight snapshot not found or not accessible",
        )
    return ChartSelectionResponse(updated=True, insight_id=insight_id)
