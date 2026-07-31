"""Business Insight project resolver.

Resolves a natural-language question asked from the Business Insight page
onto the single most confident authorized project, using the same source/column
scoring model as Project Insights but filtering candidates by authorization
*before* scoring. The resolver never emits SQL and never asks the user to pick
a project.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role
from app.models.project import Project, ProjectMember
from app.services.project_source_resolver import (
    ResolverResult,
    resolve_project_source,
)


@dataclass
class ProjectResolveResult:
    status: str  # "resolved" | "no_match"
    project_id: int | None = None
    project_name: str | None = None
    confidence: float = 0.0
    reason: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)


async def _authorized_project_ids(
    session: AsyncSession, context: RequestContext
) -> list[tuple[int, str]]:
    """Return the (id, name) of all projects the caller may access."""
    stmt = select(Project.id, Project.name).where(
        Project.tenant_id == context.tenant_id
    )

    # Platform/tenant admins can reach every project in the tenant.
    if context.role not in (
        Role.ROOT_ADMIN.value,
        Role.TENANT_ADMIN.value,
        Role.ADMIN.value,
    ):
        member_sub = select(ProjectMember.project_id).where(
            ProjectMember.user_id == context.user_id,
            ProjectMember.is_active.is_(True),
        )
        stmt = stmt.where(
            or_(
                Project.owner_id == context.user_id,
                Project.is_shared.is_(True),
                Project.id.in_(member_sub),
            )
        )

    stmt = stmt.order_by(Project.name)
    rows = (await session.execute(stmt)).all()
    return [(r.id, r.name) for r in rows]


async def resolve_business_insight_project(
    session: AsyncSession,
    context: RequestContext,
    question: str,
) -> ProjectResolveResult:
    """Resolve a Business Insight question to the best authorized project.

    Filters by authorization first, then scores each project's authorized
    sources. Returns ``resolved`` only when the top project clears the same
    confidence floor used inside Project Insights; otherwise ``no_match``.
    """
    projects = await _authorized_project_ids(session, context)
    if not projects:
        return ProjectResolveResult(
            status="no_match",
            reason="You do not have access to any projects.",
        )

    # Reuse the per-project source resolver so Business Insight benefits from the
    # same column/scoring model, while keeping the cross-project decision here.
    scored: list[tuple[int, str, ResolverResult]] = []
    for pid, pname in projects:
        result = await resolve_project_source(
            session,
            tenant_id=context.tenant_id,
            project_id=pid,
            question=question,
            intent="question_answer",
        )
        scored.append((pid, pname, result))

    # Rank projects by their top source candidate score (0 if no sources).
    def _score(result: ResolverResult) -> float:
        if result.candidates:
            return float(result.candidates[0].score)
        return 0.0

    scored.sort(key=lambda x: (-_score(x[2]), x[1]))

    # The project-source resolver uses 40.0 as the outright resolve threshold.
    _RESOLVE_SCORE = 40.0

    if not scored or _score(scored[0][2]) < _RESOLVE_SCORE:
        return ProjectResolveResult(
            status="no_match",
            reason="No authorized project confidently matches this question.",
            candidates=[
                {
                    "project_id": pid,
                    "project_name": pname,
                    "status": r.status,
                    "top_score": _score(r),
                    "top_reason": r.candidates[0].reason if r.candidates else "",
                }
                for pid, pname, r in scored[:5]
            ],
        )

    top_id, top_name, top_result = scored[0]
    return ProjectResolveResult(
        status="resolved",
        project_id=top_id,
        project_name=top_name,
        confidence=top_result.confidence,
        reason=top_result.reason,
        candidates=[
            {
                "project_id": pid,
                "project_name": pname,
                "status": r.status,
                "top_score": _score(r),
            }
            for pid, pname, r in scored[:5]
        ],
    )
