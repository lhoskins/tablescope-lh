"""Helpers shared by the AI proxy feature routers.

Request signing and forwarding to the AI server, project access checks,
datasource detection, source catalogs and knowledge-graph context."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.config import get_settings
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project, ProjectMember
from app.models.saved_query import SavedQuery
from app.services import data_source_profiler
from app.services.home_intelligence import TableInfo, find_relationship_candidates
from app.services.knowledge_graph_ai_context import collect_knowledge_graph_ai_context
from app.services.llm_framework import resolve_active_routing_for_capability

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(300.0, connect=10.0)

# Map AI server paths to LLM Framework routing capabilities so proxy endpoints
# also use the active model when one is deployed.
_CAPABILITY_BY_PATH: dict[str, str | None] = {
    "/ai/project/scopes/analyze": "sql_generation",
    "/ai/dashboard/suggest": "dashboard_planning",
    "/ai/dashboard/suggest-multi": "dashboard_planning",
    "/ai/query/generate": "sql_generation",
    "/ai/query/match": "sql_generation",
    "/ai/project/relationships/generate": "sql_generation",
    "/ai/index/document": None,
    "/ai/index/reference": None,
}


def _sign_payload(payload: dict[str, Any], secret: str) -> str:
    """Generate HMAC-SHA256 signature for a request payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(
        secret.encode(), canonical.encode(), hashlib.sha256,
    ).hexdigest()


async def _forward_to_ai(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Sign and forward request to the AI server."""
    settings = get_settings()
    if not settings.tablescope_ai_enabled or not settings.tablescope_ai_api_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI server is not configured",
        )

    capability = _CAPABILITY_BY_PATH.get(path)
    if capability:
        routing = await resolve_active_routing_for_capability(capability)
        payload["model"] = routing.model
        payload["llm_target_url"] = routing.llm_target_url
        payload["routing_version"] = routing.version
        payload["capability"] = capability

    payload["timestamp"] = time.time()
    payload["signature"] = _sign_payload(payload, settings.tablescope_ai_signing_secret)

    url = f"{settings.tablescope_ai_api_url}{path}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            detail = str(e)
            if e.response.content:
                try:
                    detail = e.response.json().get("detail", detail)
                except Exception:
                    detail = e.response.text[:500] or detail
            raise HTTPException(status_code=e.response.status_code, detail=detail) from e
        except httpx.RequestError as e:
            logger.error("AI server unreachable: %s", e)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI server is unreachable",
            ) from e


async def _authorize_project_access(
    session: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
) -> Project:
    """Verify ``user_id`` has access to ``project_id`` within ``tenant_id``.

    The id-based core of the project access check (TS-ISO-003's "strongest
    existing pattern"), factored out so callers that don't have a full
    ``RequestContext`` -- e.g. an internal callback authenticated by HMAC
    signature instead of a user JWT, see ``ai_proxy_permissions.py`` -- can
    reuse the exact same rule instead of re-implementing it. A shared
    project requires OWNERSHIP OR ACTIVE MEMBERSHIP, not merely same-tenant:
    ``is_shared`` controls discoverability/presentation, not automatic
    tenant-wide authorization (see the isolation security assessment's
    authoritative access policy).
    """
    stmt = select(Project).where(
        Project.id == project_id,
        Project.tenant_id == tenant_id,
    )
    result = await session.execute(stmt)
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found in your tenant",
        )

    if project.owner_id == user_id:
        return project

    member_stmt = select(ProjectMember).where(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == user_id,
        ProjectMember.is_active.is_(True),
    )
    member_result = await session.execute(member_stmt)
    if member_result.scalar_one_or_none():
        return project

    if project.is_shared:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this project",
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This is a private project and you are not the owner",
    )


async def _check_project_access(
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
) -> Project:
    """Verify user has access to the project within their tenant."""
    return await _authorize_project_access(
        session,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=project_id,
    )


def _detect_datasource(sql: str, allowed_tables: list[str]) -> str | None:
    """Find which datasource view_name is referenced in the generated SQL.

    An AI-generated table must never be left with a blank source: a blank
    ``left_datasource`` makes the All Tables row show no Source and causes a
    "no datasource associated" error when a query is built from it. When no
    referenced table can be matched we fall back to the first allowed table so
    the query still binds to a real, executable datasource.
    """
    sql_upper = sql.upper()
    for table in allowed_tables:
        # Check for table name in FROM/JOIN clauses (with or without quotes)
        if table.upper() in sql_upper or f'"{table}"'.upper() in sql_upper:
            return table
    return allowed_tables[0] if allowed_tables else None


async def _build_source_catalog(
    session: AsyncSession,
    context: RequestContext,
    *,
    project_id: int,
) -> list[dict[str, Any]]:
    """Build the AI source catalog (data sources + saved queries) for a project.

    Each entry carries the source name, its known columns, a short
    description, and -- when the source has one -- a data profile summary
    (row count, date range, a few categorical columns' distinct values) read
    from the profile every upload already computes, so the AI server can
    semantically match the user's request to real project sources, and
    ground SQL generation and the "why" investigation planner in what the
    data actually contains instead of inventing columns, guessing an
    unsupported date window, or assuming a trend exists.
    """
    catalog: list[dict[str, Any]] = []

    ds_rows = (
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.project_id == project_id,
                FileSourceMeta.tenant_id == context.tenant_id,
                FileSourceMeta.archived.is_(False),
            )
        )
    ).all()

    profiles: dict[str, str] = {}
    try:
        profiles = await data_source_profiler.profile_sources(session, list(ds_rows))
    except Exception as exc:  # pragma: no cover - defensive, profiling is best-effort
        logger.debug("Source profiling failed, continuing without it: %s", exc)

    for ds in ds_rows:
        columns = [
            str(c.get("name"))
            for c in (ds.column_types or [])
            if isinstance(c, dict) and c.get("name")
        ]
        description = ""
        if isinstance(ds.ai_metadata, dict):
            description = str(ds.ai_metadata.get("summary") or "")
        catalog.append(
            {
                "name": ds.view_name,
                "columns": columns,
                "description": description or None,
                "kind": "table",
                "profile_summary": profiles.get(ds.view_name),
            }
        )

    query_rows = (
        await session.scalars(
            select(SavedQuery).where(SavedQuery.project_id == project_id)
        )
    ).all()
    for q in query_rows:
        catalog.append(
            {
                "name": q.name,
                "columns": [],
                "description": (q.description or "")[:200] or None,
                "kind": "query",
            }
        )

    return catalog


async def _kg_context(
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
    *,
    max_items: int = 20,
) -> dict[str, Any]:
    """Collect the project's Knowledge Graph context for AI generation.

    Best-effort: a graph that fails to load must never block dashboard/query
    generation, so any error yields an empty context block.
    """
    try:
        return await collect_knowledge_graph_ai_context(
            session,
            tenant_id=context.tenant_id,
            project_id=project_id,
            user_id=context.user_id,
            max_items=max_items,
        )
    except Exception:  # context is optional enrichment
        logger.exception(
            "Failed to collect Knowledge Graph context for project %s", project_id,
        )
        return {}


def _kg_context_chips(kg: dict[str, Any]) -> dict[str, Any]:
    """Compact, chip-friendly KG summary for dashboard preview cards.

    Returns short title lists (not full objects) the frontend renders as chips.
    """
    def _titles(key: str, cap: int = 4) -> list[str]:
        items = kg.get(key) or []
        out: list[str] = []
        for it in items:
            title = str((it or {}).get("title") or "").strip()
            if title and title not in out:
                out.append(title)
            if len(out) >= cap:
                break
        return out

    return {
        "risks": _titles("risks"),
        "opportunities": _titles("opportunities"),
        "gaps": _titles("gaps"),
        "measuredKpis": _titles("measured_kpis"),
        "recommendedKpis": _titles("recommended_kpis"),
        "governingDocuments": _titles("governing_documents"),
    }


def _relationship_hints(sources: list[FileSourceMeta]) -> list[dict[str, Any]]:
    """Evidence-backed join candidates between a project's datasources.

    Reuses the exact join-discovery engine Home Intelligence already relies
    on (``find_relationship_candidates`` -- exact-key-name matches at
    minimum, upgraded by sampled value containment when available) so
    dashboard/widget SQL generation can be told about a real relationship
    like two monthly tables sharing a ``month`` column, instead of being
    silently restricted to one table per widget with no way to combine
    e.g. actuals and a forecast that live in separate sources.

    Best-effort: relationship discovery is enrichment, never a hard
    dependency -- a failure here must not block dashboard generation.
    """
    try:
        tables = [
            TableInfo(
                view_name=source.view_name,
                columns=[(str(c.get("name")), str(c.get("type") or "unknown")) for c in (source.column_types or []) if isinstance(c, dict) and c.get("name")],
            )
            for source in sources
        ]
        return find_relationship_candidates(tables)
    except Exception:  # relationship evidence is optional enrichment
        logger.exception("Failed to discover relationship candidates for %d source(s)", len(sources))
        return []


def _shorten_ai_name(prompt: str) -> str:
    """Convert an AI prompt into a short, clean query/widget title.

    Examples:
        "Generate a query showing total revenue by category." → "AI - Total Revenue by Category"
        "Generate a dashboard with total revenue, total orders, ..." → "AI - Total Revenue, Total Orders"
        "Show monthly sales trend" → "AI - Monthly Sales Trend"
    """
    import re as _re

    s = prompt.strip().rstrip(".")

    # Strip common AI prompt prefixes
    s = _re.sub(
        r"^(?:generate|create|show|build|make|give me|write|produce)"
        r"\s+(?:a\s+)?(?:query|dashboard|report|chart|table|widget|view)?"
        r"\s*(?:showing|with|for|of|that shows|to show|displaying)?\s*",
        "", s, flags=_re.IGNORECASE,
    ).strip()

    # If the result starts with a SELECT statement, just use the first meaningful part
    if _re.match(r"^SELECT\b", s, _re.IGNORECASE):
        s = "Custom SQL Query"

    # Title-case and prefix
    if s:
        s = s.title()
        # Preserve common lowercase words
        for word in ("by", "of", "and", "the", "in", "for", "with", "to", "a"):
            s = _re.sub(rf"\b{word.title()}\b", word, s)
        # Ensure first char is uppercase
        s = s[0].upper() + s[1:]
    else:
        s = "Query"

    return f"AI - {s}"
