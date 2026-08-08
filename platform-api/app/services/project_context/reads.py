from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.auth.rbac import Role, has_role
from app.models.project import ProjectMember
from app.models.project_context import (
    ProjectBusinessContext,
    ProjectContextAuditEvent,
)

from .base import ProjectContextBase


class ReadsMixin(ProjectContextBase):
    """ProjectContextService mixin."""
    async def get_full_context(self, project_id: int) -> dict[str, Any]:
        """Return a response-shaped dict with settings, goals, metrics, risks, and permissions."""
        project = await self._require_project(project_id)
        can_edit = False
        if project.owner_id == self.context.user_id or has_role(self.context.role, Role.ADMIN):
            can_edit = True
        else:
            member = await self.session.scalar(
                select(ProjectMember).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == self.context.user_id,
                    ProjectMember.is_active.is_(True),
                )
            )
            if member is not None and member.role in ("editor", "admin", "owner"):
                can_edit = True

        settings = await self.session.scalar(
            select(ProjectBusinessContext).where(
                ProjectBusinessContext.tenant_id == self.context.tenant_id,
                ProjectBusinessContext.project_id == project_id,
            )
        )
        goals = await self.list_goals(project_id)
        metrics = await self.list_metrics(project_id)
        risks = await self.list_risks(project_id)

        candidates = (
            ([settings.updated_at] if settings else [])
            + [g.updated_at for g in goals]
            + [m.updated_at for m in metrics]
            + [r.updated_at for r in risks]
        )
        latest_updated = max(
            [d for d in candidates if d is not None],
            default=None,
        )

        return {
            "settings": settings,
            "goals": goals,
            "metrics": metrics,
            "risks": risks,
            "permissions": {"can_edit": can_edit, "can_archive": can_edit},
            "version": settings.version if settings else 0,
            "last_updated_at": latest_updated,
        }


    async def list_audit(
        self, project_id: int, *, limit: int = 100, offset: int = 0
    ) -> tuple[list[ProjectContextAuditEvent], int]:
        await self._require_project(project_id)
        total = await self.session.scalar(
            select(func.count(ProjectContextAuditEvent.id)).where(
                ProjectContextAuditEvent.tenant_id == self.context.tenant_id,
                ProjectContextAuditEvent.project_id == project_id,
            )
        )
        total = total or 0
        items = (
            await self.session.scalars(
                select(ProjectContextAuditEvent)
                .where(
                    ProjectContextAuditEvent.tenant_id == self.context.tenant_id,
                    ProjectContextAuditEvent.project_id == project_id,
                )
                .order_by(ProjectContextAuditEvent.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return list(items), total


