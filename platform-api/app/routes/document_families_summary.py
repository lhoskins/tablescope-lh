"""Document Family summary — AI-backed rebuild of a family's narrative."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.routes.document_families_reads import _family_relationships, _require_project
from app.services.project_graph_service import (
    get_family_members,
    get_family_node,
    log_family_event,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects/{project_id}", tags=["document-families"])


# ── Rebuild summary ──────────────────────────────────────────────────

@router.post("/document-families/{family_node_id}/rebuild-summary")
async def rebuild_family_summary(
    project_id: int,
    family_node_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
):
    await _require_project(project_id, session, context)
    node = await get_family_node(session, context.tenant_id, project_id, family_node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Family not found")

    members = await get_family_members(session, context.tenant_id, project_id, family_node_id)
    relationships = await _family_relationships(session, context.tenant_id, project_id, family_node_id)
    p = node["properties"]

    summary_data = await _call_family_summarize(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=project_id,
        family_name=node["name"],
        family_type=p.get("family_type", ""),
        business_domain=p.get("business_domain", ""),
        members=members,
        relationships=relationships,
    )
    if summary_data is None:
        raise HTTPException(status_code=502, detail="Family summarization is unavailable")

    new_props = dict(p)
    new_props["family_summary"] = summary_data.get("summary", "")
    new_props["primary_purpose"] = summary_data.get("primary_purpose", "")
    new_props["supported_kpis"] = summary_data.get("supported_kpis", [])
    new_props["related_processes"] = summary_data.get("related_processes", [])
    new_props["suggested_dashboards"] = summary_data.get("suggested_dashboards", [])
    new_props["missing_documents"] = summary_data.get("missing_documents", [])
    new_props["suggested_questions"] = summary_data.get("suggested_questions", [])
    new_props["updated_at"] = time.time()

    await session.execute(
        text("UPDATE ai_project_graph_nodes SET properties=:p WHERE id=:id"),
        {"p": json.dumps(new_props), "id": family_node_id},
    )
    log_family_event(
        "document_family_summary_rebuilt",
        tenant_id=context.tenant_id, project_id=project_id,
        family_node_id=family_node_id, user_id=context.user_id,
    )
    await session.commit()
    return {"status": "rebuilt", "family_node_id": family_node_id, **summary_data}


async def _call_family_summarize(
    tenant_id: int,
    user_id: int,
    project_id: int,
    family_name: str,
    family_type: str,
    business_domain: str,
    members: dict[str, list[dict[str, Any]]],
    relationships: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Call the dedicated /ai/family/summarize endpoint. Returns None on failure."""
    settings = get_settings()
    if not settings.tablescope_ai_enabled or not settings.tablescope_ai_api_url:
        return None

    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "project_id": project_id,
        "family_name": family_name,
        "family_type": family_type,
        "business_domain": business_domain,
        "member_documents": [
            {"name": d["name"], "summary": d.get("summary", "")}
            for d in members.get("documents", [])
        ],
        "member_datasources": [{"name": d["name"]} for d in members.get("datasources", [])],
        "member_kpis": [d["name"] for d in members.get("kpis", [])],
        "member_entities": [d["name"] for d in members.get("entities", [])],
        "relationships": relationships,
        "timestamp": time.time(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["signature"] = hmac.new(
        settings.tablescope_ai_signing_secret.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{settings.tablescope_ai_api_url}/ai/family/summarize", json=payload,
            )
        if resp.status_code != 200:
            logger.warning("family/summarize HTTP %d: %s", resp.status_code, resp.text[:200])
            return None
        return resp.json()
    except Exception as exc:
        logger.warning("family/summarize failed: %s", exc)
        return None
