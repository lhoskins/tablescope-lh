"""Persist a user's chart-family selection back into cached insight snapshots.

The modal frontend shows ``chartCandidates`` computed by the visualization engine.
When the user applies a different chart, this service updates the selected
``chart.type`` / ``chart.subtype`` and ``visualizationDecision`` in the cached
cards so the choice survives refresh, Home pins, and dashboard add.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.business_insight_result import BusinessInsightResult
from app.models.home_pin import HomePin
from app.models.intelligence_snapshot import IntelligenceSnapshot
from app.models.project_intelligence_snapshot import ProjectIntelligenceSnapshot


def _apply_selection(card: dict[str, Any], selection: dict[str, Any]) -> bool:
    """Update ``card`` with the selected visualization and return whether changed."""
    decision = selection.get("visualizationDecision") or {}
    chart_type = (
        selection.get("chartType")
        or decision.get("chartType")
        or (card.get("chart") or {}).get("type")
    )
    chart_style = (
        selection.get("chartSubtype")
        or decision.get("chartStyle")
        or (card.get("chart") or {}).get("subtype")
        or ""
    )
    if not chart_type:
        return False

    if card.get("chart") and isinstance(card["chart"], dict):
        card["chart"]["type"] = chart_type
        card["chart"]["subtype"] = chart_style
    card["visualizationDecision"] = decision or {
        "chartType": chart_type,
        "chartStyle": chart_style,
        "valueFormat": decision.get("valueFormat") or "number",
        "reason": "User-selected chart from candidate list.",
        "confidence": 1.0,
    }
    card["chartType"] = chart_type
    return True


def _update_cards(cards: list[Any], insight_id: str, selection: dict[str, Any]) -> bool:
    updated = False
    for c in cards:
        if not isinstance(c, dict):
            continue
        if str(c.get("insightId") or c.get("id") or "") == insight_id:
            if _apply_selection(c, selection):
                updated = True
    return updated


def _walk_card_groups(payload: dict[str, Any], insight_id: str, selection: dict[str, Any]) -> bool:
    updated = False
    if isinstance(payload.get("insights"), list):
        if _update_cards(payload["insights"], insight_id, selection):
            updated = True
    for group in ("risks", "trends", "opportunities"):
        if isinstance(payload.get(group), list):
            if _update_cards(payload[group], insight_id, selection):
                updated = True
    return updated


async def persist_chart_selection(
    session: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    insight_id: str,
    selection: dict[str, Any],
) -> bool:
    """Update all cached snapshots that contain this insight card."""
    updated_any = False

    # Business Insight result cache (project-scoped, shared across users).
    bis_stmt = select(BusinessInsightResult).where(
        BusinessInsightResult.tenant_id == tenant_id,
        BusinessInsightResult.project_id == project_id,
    )
    bis_rows = (await session.execute(bis_stmt)).scalars().all()
    for bis_row in bis_rows:
        payload = copy.deepcopy(bis_row.payload or {})
        if _walk_card_groups(payload, insight_id, selection):
            bis_row.payload = payload
            flag_modified(bis_row, "payload")
            updated_any = True

    # Project Intelligence snapshot (per user, per project).
    pis_stmt = select(ProjectIntelligenceSnapshot).where(
        ProjectIntelligenceSnapshot.tenant_id == tenant_id,
        ProjectIntelligenceSnapshot.user_id == user_id,
        ProjectIntelligenceSnapshot.project_id == project_id,
    )
    pis_rows = (await session.execute(pis_stmt)).scalars().all()
    for pis_row in pis_rows:
        payload = copy.deepcopy(pis_row.payload or {})
        if _walk_card_groups(payload, insight_id, selection):
            pis_row.payload = payload
            flag_modified(pis_row, "payload")
            updated_any = True

    # Home pins (frozen insight snapshots).
    hp_stmt = select(HomePin).where(
        HomePin.tenant_id == tenant_id,
        HomePin.user_id == user_id,
        HomePin.project_id == project_id,
    )
    hp_rows = (await session.execute(hp_stmt)).scalars().all()
    for hp_row in hp_rows:
        fp = copy.deepcopy(hp_row.frozen_payload or {})
        if str(fp.get("insightId") or fp.get("id") or "") == insight_id:
            if _apply_selection(fp, selection):
                hp_row.frozen_payload = fp
                flag_modified(hp_row, "frozen_payload")
                updated_any = True

    # Home/Business Intelligence snapshot (per-user aggregate of project results).
    # The insight may live inside one of the per-project result payloads rather
    # than a dedicated Business/Project snapshot.
    is_stmt = select(IntelligenceSnapshot).where(
        IntelligenceSnapshot.tenant_id == tenant_id,
        IntelligenceSnapshot.user_id == user_id,
    )
    is_row = (await session.execute(is_stmt)).scalar_one_or_none()
    if is_row is not None:
        is_payload = copy.deepcopy(is_row.payload or {})
        results = is_payload.get("results") or []
        for result in results:
            if str(result.get("projectId") or "") != str(project_id):
                continue
            if _walk_card_groups(result, insight_id, selection):
                is_row.payload = is_payload
                flag_modified(is_row, "payload")
                updated_any = True
                break

    if updated_any:
        await session.commit()
    return updated_any
