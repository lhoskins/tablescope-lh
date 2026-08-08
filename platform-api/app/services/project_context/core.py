from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, has_role
from app.models.project import Project, ProjectMember
from app.models.project_context import (
    ProjectBusinessContext,
    ProjectContextAuditEvent,
)
from app.models.user import User
from app.schemas.project_context import (
    ProjectBusinessContextUpdate,
)
from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager
from app.services.project_ai_context import invalidate_project_ai_context

from .base import ProjectContextBase

logger = logging.getLogger(__name__)


_VALID_PRIORITIES = {"low", "medium", "high", "critical"}


_VALID_GOAL_STATUSES = {"draft", "not_started", "in_progress", "active", "at_risk", "achieved", "paused", "cancelled"}


_VALID_METRIC_DIRECTIONALITY = {"higher_is_better", "lower_is_better", "neutral", "target_range", "informational"}


_VALID_METRIC_AGGREGATION = {
    "sum", "average", "min", "max", "count", "distinct_count", "ratio", "latest", "last", "custom"
}


_VALID_TARGET_TYPES = {"minimum", "maximum", "exact", "range", "increase_by", "decrease_by", "single_value", "threshold", "milestone"}


_VALID_TARGET_STATUSES = {"draft", "active", "archived"}


_VALID_LIKELIHOOD = {"rare", "unlikely", "possible", "likely", "almost_certain"}


_VALID_IMPACT = {"negligible", "insignificant", "minor", "moderate", "major", "severe", "catastrophic"}


_VALID_SEVERITY = {"low", "medium", "high", "critical"}


_VALID_RISK_STATUSES = {"open", "mitigating", "monitoring", "mitigated", "closed", "accepted"}


class ProjectContextConcurrencyError(HTTPException):
    """Raised when an optimistic version check fails."""

    def __init__(self, current_version: int, expected_version: int) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "detail": "Project context was modified by another session.",
                "current_version": current_version,
                "expected_version": expected_version,
            },
        )


class CoreMixin(ProjectContextBase):
    """ProjectContextService mixin."""
    def __init__(self, session: AsyncSession, context: RequestContext) -> None:
        self.session = session
        self.context = context


    async def _mark_knowledge_graph_stale(self, project_id: int, reason: str) -> None:
        """Mark the project's knowledge graph stale when authoritative context changes."""
        try:
            lifecycle = KnowledgeGraphLifecycleManager(self.session, self.context)
            await lifecycle.mark_stale(project_id, reason)
            await self.session.flush()
        except Exception as exc:
            # Never fail a context mutation because the graph lifecycle hook failed.
            logger.warning("Failed to mark knowledge graph stale: %s", exc)


    async def _require_project(self, project_id: int, write: bool = False) -> Project:
        """Verify project access and return the project.

        Write access requires project ownership, tenant admin, or a project
        member role of editor/admin/owner.
        """
        project = await self.session.get(Project, project_id)
        if project is None or project.tenant_id != self.context.tenant_id:
            raise HTTPException(status_code=404, detail="Project not found")

        if project.owner_id == self.context.user_id:
            return project

        if has_role(self.context.role, Role.ADMIN) or has_role(
            self.context.role, Role.TENANT_ADMIN
        ):
            # Tenant-wide admins may edit any project in the tenant.
            if write:
                return project
            return project

        member = await self.session.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == self.context.user_id,
                ProjectMember.is_active.is_(True),
            )
        )
        if member is None:
            raise HTTPException(status_code=403, detail="No access to this project")

        if write and member.role not in ("editor", "admin", "owner"):
            raise HTTPException(status_code=403, detail="Insufficient project permissions")

        return project


    async def _validate_owner(self, owner_id: int | None) -> None:
        """Ensure a supplied owner ID exists in the current tenant."""
        if owner_id is None:
            return
        user = await self.session.get(User, owner_id)
        if user is None or user.tenant_id != self.context.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Owner {owner_id} is not a member of this tenant",
            )


    def _check_version(self, current: int, expected: int | None) -> None:
        """Optimistic concurrency guard."""
        if expected is not None and current != expected:
            raise ProjectContextConcurrencyError(current, expected)


    async def _audit(
        self,
        *,
        project_id: int,
        event_type: str,
        entity_type: str,
        entity_id: int | None,
        previous_value: dict | None = None,
        new_value: dict | None = None,
        version: int | None = None,
    ) -> None:
        """Append an immutable project-context audit event."""
        self.session.add(
            ProjectContextAuditEvent(
                tenant_id=self.context.tenant_id,
                project_id=project_id,
                actor_user_id=self.context.user_id,
                actor_type="user",
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                previous_value=previous_value,
                new_value=new_value,
                version=version,
            )
        )


    async def get_or_create_settings(self, project_id: int) -> ProjectBusinessContext:
        """Return existing settings or a transient default for the project."""
        await self._require_project(project_id)
        settings = await self.session.scalar(
            select(ProjectBusinessContext).where(
                ProjectBusinessContext.tenant_id == self.context.tenant_id,
                ProjectBusinessContext.project_id == project_id,
            )
        )
        if settings is None:
            settings = ProjectBusinessContext(
                tenant_id=self.context.tenant_id,
                project_id=project_id,
                version=0,
            )
            # Not flushed here; callers decide whether to persist.
            self.session.add(settings)
        return settings


    async def update_settings(
        self, project_id: int, payload: ProjectBusinessContextUpdate
    ) -> ProjectBusinessContext:
        """Update project business context settings."""
        await self._require_project(project_id, write=True)
        await self._validate_owner(payload.business_owner_id)

        settings = await self.get_or_create_settings(project_id)
        self._check_version(settings.version, payload.expected_version)

        previous = settings.to_redacted_dict() if settings.id else None

        for field in (
            "business_owner_id",
            "business_function",
            "industry",
            "purpose",
            "timezone",
            "currency",
            "reporting_cadence",
            "fiscal_year_start_month",
            "ai_context_enabled",
            "ai_instructions",
            "interpretation_notes",
        ):
            value = getattr(payload, field)
            if value is not None:
                setattr(settings, field, value)

        settings.version += 1
        settings.updated_by = self.context.user_id
        self.session.add(settings)
        await self.session.flush()
        await self.session.refresh(settings)

        new = settings.to_redacted_dict()
        invalidate_project_ai_context(self.context.tenant_id, project_id)
        await self._mark_knowledge_graph_stale(project_id, "Project context updated")
        await self._audit(
            project_id=project_id,
            event_type="project_context.settings_updated",
            entity_type="settings",
            entity_id=settings.id,
            previous_value=previous,
            new_value=new,
            version=settings.version,
        )
        return settings


