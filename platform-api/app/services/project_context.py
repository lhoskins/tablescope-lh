"""Project business context service.

Handles CRUD, ordering, optimistic concurrency, relationship validation,
audit logging, and AI context building for project goals, metrics, targets,
and risks.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.context import RequestContext
from app.auth.rbac import Role, has_role
from app.models.project import Project, ProjectMember
from app.models.project_context import (
    ProjectBusinessContext,
    ProjectContextAuditEvent,
    ProjectGoal,
    ProjectGoalMetricLink,
    ProjectGoalRiskLink,
    ProjectMetric,
    ProjectMetricTarget,
    ProjectRisk,
    ProjectRiskMetricLink,
)
from app.models.user import User
from app.schemas.project_context import (
    ProjectBusinessContextUpdate,
    ProjectGoalCreate,
    ProjectGoalUpdate,
    ProjectMetricCreate,
    ProjectMetricTargetCreate,
    ProjectMetricTargetUpdate,
    ProjectMetricUpdate,
    ProjectRiskCreate,
    ProjectRiskUpdate,
    ReorderRequest,
)
from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager
from app.services.project_ai_context import invalidate_project_ai_context
from app.services.risk_rating import RATING_MATRIX_VERSION, compute_severity

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


class ProjectContextService:
    """CRUD, validation, ordering, and audit for project business context."""

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

    # ── Goals ────────────────────────────────────────────────────────────

    async def list_goals(self, project_id: int) -> list[ProjectGoal]:
        await self._require_project(project_id)
        result = await self.session.scalars(
            select(ProjectGoal)
            .options(
                selectinload(ProjectGoal.metric_links),
                selectinload(ProjectGoal.risk_links),
            )
            .where(
                ProjectGoal.tenant_id == self.context.tenant_id,
                ProjectGoal.project_id == project_id,
                ProjectGoal.active.is_(True),
            )
            .order_by(ProjectGoal.position)
        )
        return [g for g in result]

    async def _validate_goal_payload(self, payload: ProjectGoalCreate | ProjectGoalUpdate) -> None:
        if hasattr(payload, "priority") and payload.priority is not None:
            if payload.priority not in _VALID_PRIORITIES:
                raise HTTPException(
                    status_code=400, detail=f"Invalid priority: {payload.priority}"
                )
        if hasattr(payload, "status") and payload.status is not None:
            if payload.status not in _VALID_GOAL_STATUSES:
                raise HTTPException(
                    status_code=400, detail=f"Invalid status: {payload.status}"
                )
        await self._validate_owner(payload.owner_id)

    async def _sync_goal_links(self, goal: ProjectGoal, metric_ids: list[int] | None, risk_ids: list[int] | None) -> None:
        if metric_ids is not None:
            await self._validate_link_ids(metric_ids, ProjectMetric)
            await self.session.execute(
                delete(ProjectGoalMetricLink).where(
                    ProjectGoalMetricLink.goal_id == goal.id
                )
            )
            for mid in set(metric_ids):
                self.session.add(
                    ProjectGoalMetricLink(goal_id=goal.id, metric_id=mid)
                )
        if risk_ids is not None:
            await self._validate_link_ids(risk_ids, ProjectRisk)
            await self.session.execute(
                delete(ProjectGoalRiskLink).where(
                    ProjectGoalRiskLink.goal_id == goal.id
                )
            )
            for rid in set(risk_ids):
                self.session.add(
                    ProjectGoalRiskLink(goal_id=goal.id, risk_id=rid)
                )

    async def _validate_link_ids(self, ids: list[int], model: type) -> None:
        if not ids:
            return
        rows: list[Any] = list(
            await self.session.scalars(
                select(model).where(
                    model.id.in_(set(ids)),  # type: ignore[attr-defined]
                    model.tenant_id == self.context.tenant_id,  # type: ignore[attr-defined]
                )
            )
        )
        found = {r.id for r in rows}
        missing = set(ids) - found
        if missing:
            raise HTTPException(
                status_code=400, detail=f"Invalid linked {model.__name__} ids: {sorted(missing)}"
            )

    async def create_goal(self, project_id: int, payload: ProjectGoalCreate) -> ProjectGoal:
        await self._require_project(project_id, write=True)
        await self._validate_goal_payload(payload)

        max_position = await self.session.scalar(
            select(ProjectGoal.position)
            .where(ProjectGoal.project_id == project_id)
            .order_by(ProjectGoal.position.desc())
            .limit(1)
        ) or 0

        goal = ProjectGoal(
            tenant_id=self.context.tenant_id,
            project_id=project_id,
            title=payload.title,
            description=payload.description,
            category=payload.category,
            priority=payload.priority,
            owner_id=payload.owner_id,
            status=payload.status,
            start_date=payload.start_date,
            target_date=payload.target_date,
            position=max_position + 1,
        )
        self.session.add(goal)
        await self.session.flush()
        await self._sync_goal_links(goal, payload.linked_metric_ids, payload.linked_risk_ids)
        await self.session.flush()
        invalidate_project_ai_context(self.context.tenant_id, project_id)
        await self._mark_knowledge_graph_stale(project_id, "Project context updated")

        await self._audit(
            project_id=project_id,
            event_type="project_context.goal_created",
            entity_type="goal",
            entity_id=goal.id,
            new_value=goal.to_redacted_dict(),
            version=goal.version,
        )
        return await self.get_goal(project_id, goal.id)

    async def get_goal(self, project_id: int, goal_id: int) -> ProjectGoal:
        await self._require_project(project_id)
        goal = await self.session.scalar(
            select(ProjectGoal)
            .options(
                selectinload(ProjectGoal.metric_links),
                selectinload(ProjectGoal.risk_links),
            )
            .where(
                ProjectGoal.id == goal_id,
                ProjectGoal.tenant_id == self.context.tenant_id,
            )
        )
        if goal is None or goal.project_id != project_id or goal.tenant_id != self.context.tenant_id:
            raise HTTPException(status_code=404, detail="Goal not found")
        return goal

    async def update_goal(
        self, project_id: int, goal_id: int, payload: ProjectGoalUpdate
    ) -> ProjectGoal:
        await self._require_project(project_id, write=True)
        goal = await self.get_goal(project_id, goal_id)
        self._check_version(goal.version, payload.expected_version)
        await self._validate_goal_payload(payload)

        previous = goal.to_redacted_dict()

        for field in (
            "title",
            "description",
            "category",
            "priority",
            "owner_id",
            "status",
            "start_date",
            "target_date",
            "active",
        ):
            value = getattr(payload, field)
            if value is not None:
                setattr(goal, field, value)

        goal.version += 1
        if payload.linked_metric_ids is not None or payload.linked_risk_ids is not None:
            await self._sync_goal_links(
                goal,
                payload.linked_metric_ids if payload.linked_metric_ids is not None else None,
                payload.linked_risk_ids if payload.linked_risk_ids is not None else None,
            )

        await self.session.flush()
        invalidate_project_ai_context(self.context.tenant_id, project_id)
        await self._mark_knowledge_graph_stale(project_id, "Project context updated")

        await self._audit(
            project_id=project_id,
            event_type="project_context.goal_updated"
            if goal.active
            else "project_context.goal_archived",
            entity_type="goal",
            entity_id=goal.id,
            previous_value=previous,
            new_value=goal.to_redacted_dict(),
            version=goal.version,
        )
        return await self.get_goal(project_id, goal.id)

    async def delete_goal(self, project_id: int, goal_id: int) -> None:
        await self._require_project(project_id, write=True)
        goal = await self.get_goal(project_id, goal_id)
        previous = goal.to_redacted_dict()

        metric_ids = {link.metric_id for link in goal.metric_links}
        risk_ids = {link.risk_id for link in goal.risk_links}

        # Soft-delete metrics that are exclusively linked to this criterion; otherwise
        # just detach them from the criterion being archived.
        if metric_ids:
            metrics_with_other_links = {
                row
                for row in await self.session.scalars(
                    select(ProjectGoalMetricLink.metric_id)
                    .join(ProjectGoal, ProjectGoal.id == ProjectGoalMetricLink.goal_id)
                    .where(
                        ProjectGoalMetricLink.metric_id.in_(metric_ids),
                        ProjectGoalMetricLink.goal_id != goal.id,
                        ProjectGoal.active.is_(True),
                    )
                )
            }
            metrics = (
                await self.session.scalars(
                    select(ProjectMetric).where(ProjectMetric.id.in_(metric_ids))
                )
            ).all()
            for metric in metrics:
                if metric.id not in metrics_with_other_links:
                    metric.active = False
                    metric.version += 1
                elif metric.success_criterion_id == goal.id:
                    metric.success_criterion_id = None
                    metric.version += 1
            await self.session.execute(
                delete(ProjectGoalMetricLink).where(
                    ProjectGoalMetricLink.goal_id == goal.id,
                    ProjectGoalMetricLink.metric_id.in_(metric_ids),
                )
            )

        # Soft-delete risks that are exclusively linked to this criterion.
        if risk_ids:
            risks_with_other_links = {
                row
                for row in await self.session.scalars(
                    select(ProjectGoalRiskLink.risk_id)
                    .join(ProjectGoal, ProjectGoal.id == ProjectGoalRiskLink.goal_id)
                    .where(
                        ProjectGoalRiskLink.risk_id.in_(risk_ids),
                        ProjectGoalRiskLink.goal_id != goal.id,
                        ProjectGoal.active.is_(True),
                    )
                )
            }
            risks = (
                await self.session.scalars(
                    select(ProjectRisk).where(ProjectRisk.id.in_(risk_ids))
                )
            ).all()
            for risk in risks:
                if risk.id not in risks_with_other_links:
                    risk.active = False
                    risk.version += 1
            await self.session.execute(
                delete(ProjectGoalRiskLink).where(
                    ProjectGoalRiskLink.goal_id == goal.id,
                    ProjectGoalRiskLink.risk_id.in_(risk_ids),
                )
            )

        goal.active = False
        goal.version += 1
        await self.session.flush()
        invalidate_project_ai_context(self.context.tenant_id, project_id)
        await self._mark_knowledge_graph_stale(project_id, "Project context updated")
        await self._audit(
            project_id=project_id,
            event_type="project_context.goal_archived",
            entity_type="goal",
            entity_id=goal.id,
            previous_value=previous,
            new_value={"active": False},
            version=goal.version,
        )

    async def reorder_goals(self, project_id: int, payload: ReorderRequest) -> None:
        await self._require_project(project_id, write=True)
        goals = (
            await self.session.scalars(
                select(ProjectGoal).where(
                    ProjectGoal.tenant_id == self.context.tenant_id,
                    ProjectGoal.project_id == project_id,
                    ProjectGoal.active.is_(True),
                )
            )
        ).all()
        goal_map = {g.id: g for g in goals}
        if set(payload.ids) != set(goal_map):
            raise HTTPException(status_code=400, detail="Reorder ids do not match active goals")
        for idx, goal_id in enumerate(payload.ids):
            goal_map[goal_id].position = idx
            goal_map[goal_id].version += 1
        await self.session.flush()
        invalidate_project_ai_context(self.context.tenant_id, project_id)
        await self._mark_knowledge_graph_stale(project_id, "Project context updated")

    # ── Metrics ───────────────────────────────────────────────────────────

    async def list_metrics(self, project_id: int) -> list[ProjectMetric]:
        await self._require_project(project_id)
        result = await self.session.scalars(
            select(ProjectMetric)
            .options(selectinload(ProjectMetric.targets))
            .where(
                ProjectMetric.tenant_id == self.context.tenant_id,
                ProjectMetric.project_id == project_id,
                ProjectMetric.active.is_(True),
            )
            .order_by(ProjectMetric.position)
        )
        return [m for m in result]

    async def _validate_metric_payload(
        self,
        payload: ProjectMetricCreate | ProjectMetricUpdate,
        *,
        project_id: int,
    ) -> None:
        if hasattr(payload, "directionality") and payload.directionality is not None:
            if payload.directionality not in _VALID_METRIC_DIRECTIONALITY:
                raise HTTPException(status_code=400, detail=f"Invalid directionality: {payload.directionality}")
        if hasattr(payload, "aggregation") and payload.aggregation is not None:
            if payload.aggregation not in _VALID_METRIC_AGGREGATION:
                raise HTTPException(status_code=400, detail=f"Invalid aggregation: {payload.aggregation}")
        if hasattr(payload, "source_query_id") and payload.source_query_id is not None:
            # Optional lightweight existence check when source type points to a query.
            from app.models.saved_query import SavedQuery

            query = await self.session.get(SavedQuery, payload.source_query_id)
            if query is None or query.project_id != project_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid source_query_id: {payload.source_query_id}",
                )
        await self._validate_owner(payload.owner_id if hasattr(payload, "owner_id") else None)
        if getattr(payload, "success_criterion_id", None) is not None:
            await self._validate_success_criterion_id(project_id, payload.success_criterion_id)

    async def _validate_success_criterion_id(
        self, project_id: int, goal_id: int | None
    ) -> None:
        if goal_id is None:
            return
        goal = await self.session.get(ProjectGoal, goal_id)
        if (
            goal is None
            or goal.project_id != project_id
            or goal.tenant_id != self.context.tenant_id
            or not goal.active
        ):
            raise HTTPException(status_code=400, detail=f"Invalid success_criterion_id: {goal_id}")

    async def _sync_metric_success_criterion_link(self, metric: ProjectMetric) -> None:
        """Keep the legacy M:N goal-metric link in sync with success_criterion_id."""
        await self.session.execute(
            delete(ProjectGoalMetricLink).where(
                ProjectGoalMetricLink.metric_id == metric.id
            )
        )
        if metric.success_criterion_id is not None:
            self.session.add(
                ProjectGoalMetricLink(
                    goal_id=metric.success_criterion_id,
                    metric_id=metric.id,
                )
            )

    async def _check_metric_name_unique(
        self, project_id: int, name: str, exclude_id: int | None = None
    ) -> None:
        stmt = select(ProjectMetric).where(
            ProjectMetric.tenant_id == self.context.tenant_id,
            ProjectMetric.project_id == project_id,
            ProjectMetric.active.is_(True),
            ProjectMetric.name == name,
        )
        if exclude_id is not None:
            stmt = stmt.where(ProjectMetric.id != exclude_id)
        existing = await self.session.scalar(stmt)
        if existing is not None:
            raise HTTPException(
                status_code=400, detail=f"Metric name '{name}' already exists in this project"
            )

    async def create_metric(self, project_id: int, payload: ProjectMetricCreate) -> ProjectMetric:
        await self._require_project(project_id, write=True)
        await self._validate_metric_payload(payload, project_id=project_id)
        await self._check_metric_name_unique(project_id, payload.name)

        max_position = (
            await self.session.scalar(
                select(ProjectMetric.position)
                .where(ProjectMetric.project_id == project_id)
                .order_by(ProjectMetric.position.desc())
                .limit(1)
            )
            or 0
        )

        metric = ProjectMetric(
            tenant_id=self.context.tenant_id,
            project_id=project_id,
            name=payload.name,
            description=payload.description,
            business_definition=payload.business_definition,
            unit=payload.unit,
            format=payload.format,
            directionality=payload.directionality,
            aggregation=payload.aggregation,
            source_type=payload.source_type,
            source_query_id=payload.source_query_id,
            source_mapping=payload.source_mapping or {},
            expression=payload.expression,
            success_criterion_id=payload.success_criterion_id,
            owner_id=payload.owner_id,
            cadence=payload.cadence,
            position=max_position + 1,
        )
        self.session.add(metric)
        await self.session.flush()
        await self._sync_metric_success_criterion_link(metric)
        await self.session.flush()

        for t_payload in payload.targets:
            await self._create_target(metric, t_payload)

        await self.session.flush()
        invalidate_project_ai_context(self.context.tenant_id, project_id)
        await self._mark_knowledge_graph_stale(project_id, "Project context updated")

        await self._audit(
            project_id=project_id,
            event_type="project_context.metric_created",
            entity_type="metric",
            entity_id=metric.id,
            new_value=metric.to_redacted_dict(),
            version=metric.version,
        )
        return await self.get_metric(project_id, metric.id)

    async def get_metric(self, project_id: int, metric_id: int) -> ProjectMetric:
        await self._require_project(project_id)
        metric = await self.session.scalar(
            select(ProjectMetric)
            .options(selectinload(ProjectMetric.targets))
            .where(
                ProjectMetric.id == metric_id,
                ProjectMetric.tenant_id == self.context.tenant_id,
            )
        )
        if (
            metric is None
            or metric.project_id != project_id
            or metric.tenant_id != self.context.tenant_id
        ):
            raise HTTPException(status_code=404, detail="Metric not found")
        return metric

    async def update_metric(
        self, project_id: int, metric_id: int, payload: ProjectMetricUpdate
    ) -> ProjectMetric:
        await self._require_project(project_id, write=True)
        metric = await self.get_metric(project_id, metric_id)
        self._check_version(metric.version, payload.expected_version)
        await self._validate_metric_payload(payload, project_id=project_id)

        if payload.name is not None:
            await self._check_metric_name_unique(project_id, payload.name, exclude_id=metric.id)

        previous = metric.to_redacted_dict()

        for field in (
            "name",
            "description",
            "business_definition",
            "unit",
            "format",
            "directionality",
            "aggregation",
            "source_type",
            "source_query_id",
            "source_mapping",
            "expression",
            "success_criterion_id",
            "owner_id",
            "cadence",
            "active",
        ):
            value = getattr(payload, field)
            if value is not None:
                if field == "source_mapping" and value is not None:
                    value = value or {}
                setattr(metric, field, value)

        metric.version += 1
        await self.session.flush()
        if payload.success_criterion_id is not None:
            await self._sync_metric_success_criterion_link(metric)
            await self.session.flush()
        invalidate_project_ai_context(self.context.tenant_id, project_id)
        await self._mark_knowledge_graph_stale(project_id, "Project context updated")

        await self._audit(
            project_id=project_id,
            event_type="project_context.metric_updated"
            if metric.active
            else "project_context.metric_archived",
            entity_type="metric",
            entity_id=metric.id,
            previous_value=previous,
            new_value=metric.to_redacted_dict(),
            version=metric.version,
        )
        return await self.get_metric(project_id, metric.id)

    async def delete_metric(self, project_id: int, metric_id: int) -> None:
        await self._require_project(project_id, write=True)
        metric = await self.get_metric(project_id, metric_id)
        previous = metric.to_redacted_dict()
        metric.active = False
        metric.version += 1
        await self.session.flush()
        invalidate_project_ai_context(self.context.tenant_id, project_id)
        await self._mark_knowledge_graph_stale(project_id, "Project context updated")
        await self._audit(
            project_id=project_id,
            event_type="project_context.metric_archived",
            entity_type="metric",
            entity_id=metric.id,
            previous_value=previous,
            new_value={"active": False},
            version=metric.version,
        )

    async def reorder_metrics(self, project_id: int, payload: ReorderRequest) -> None:
        await self._require_project(project_id, write=True)
        metrics = (
            await self.session.scalars(
                select(ProjectMetric).where(
                    ProjectMetric.tenant_id == self.context.tenant_id,
                    ProjectMetric.project_id == project_id,
                    ProjectMetric.active.is_(True),
                )
            )
        ).all()
        metric_map = {m.id: m for m in metrics}
        if set(payload.ids) != set(metric_map):
            raise HTTPException(status_code=400, detail="Reorder ids do not match active metrics")
        for idx, metric_id in enumerate(payload.ids):
            metric_map[metric_id].position = idx
            metric_map[metric_id].version += 1
        await self.session.flush()
        invalidate_project_ai_context(self.context.tenant_id, project_id)
        await self._mark_knowledge_graph_stale(project_id, "Project context updated")

    # ── Targets ──────────────────────────────────────────────────────────

    async def _validate_target_payload(self, payload: ProjectMetricTargetCreate | ProjectMetricTargetUpdate) -> None:
        if payload.target_type not in _VALID_TARGET_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid target type: {payload.target_type}")
        if payload.status is not None and payload.status not in _VALID_TARGET_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid target status: {payload.status}")

        if payload.target_type in ("minimum", "increase_by"):
            if payload.comparison_operator is not None and payload.comparison_operator not in (">=", ">"):
                raise HTTPException(status_code=400, detail="Minimum targets require >= or >")
        if payload.target_type in ("maximum", "decrease_by"):
            if payload.comparison_operator is not None and payload.comparison_operator not in ("<=", "<"):
                raise HTTPException(status_code=400, detail="Maximum targets require <= or <")
        if payload.target_type == "exact":
            if payload.comparison_operator is not None and payload.comparison_operator != "=":
                raise HTTPException(status_code=400, detail="Exact targets require =")
        if payload.target_type == "range":
            if payload.lower_bound is None or payload.upper_bound is None:
                raise HTTPException(status_code=400, detail="Range targets require lower_bound and upper_bound")
            if payload.lower_bound > payload.upper_bound:
                raise HTTPException(status_code=400, detail="lower_bound must be <= upper_bound")

        if payload.effective_start and payload.effective_end and payload.effective_start > payload.effective_end:
            raise HTTPException(status_code=400, detail="effective_start must be <= effective_end")

    async def _create_target(
        self, metric: ProjectMetric, payload: ProjectMetricTargetCreate
    ) -> ProjectMetricTarget:
        await self._validate_target_payload(payload)
        max_position = (
            await self.session.scalar(
                select(ProjectMetricTarget.position)
                .where(ProjectMetricTarget.metric_id == metric.id)
                .order_by(ProjectMetricTarget.position.desc())
                .limit(1)
            )
            or 0
        )
        target = ProjectMetricTarget(
            tenant_id=self.context.tenant_id,
            project_id=metric.project_id,
            metric_id=metric.id,
            target_type=payload.target_type,
            target_value=payload.target_value,
            lower_bound=payload.lower_bound,
            upper_bound=payload.upper_bound,
            comparison_operator=payload.comparison_operator or _default_comparison(payload.target_type),
            warning_threshold=payload.warning_threshold,
            critical_threshold=payload.critical_threshold,
            baseline=payload.baseline,
            effective_start=payload.effective_start,
            effective_end=payload.effective_end,
            period=payload.period,
            notes=payload.notes,
            status=payload.status,
            position=max_position + 1,
        )
        self.session.add(target)
        return target

    async def create_target(
        self, project_id: int, metric_id: int, payload: ProjectMetricTargetCreate
    ) -> ProjectMetricTarget:
        await self._require_project(project_id, write=True)
        metric = await self.get_metric(project_id, metric_id)
        target = await self._create_target(metric, payload)
        await self.session.flush()
        await self.session.refresh(target)
        invalidate_project_ai_context(self.context.tenant_id, project_id)
        await self._mark_knowledge_graph_stale(project_id, "Project context updated")
        await self._audit(
            project_id=project_id,
            event_type="project_context.target_created",
            entity_type="target",
            entity_id=target.id,
            new_value=target.to_redacted_dict(),
            version=target.version,
        )
        return target

    async def update_target(
        self, project_id: int, metric_id: int, target_id: int, payload: ProjectMetricTargetUpdate
    ) -> ProjectMetricTarget:
        await self._require_project(project_id, write=True)
        await self.get_metric(project_id, metric_id)
        target = await self.session.get(ProjectMetricTarget, target_id)
        if (
            target is None
            or target.metric_id != metric_id
            or target.project_id != project_id
            or target.tenant_id != self.context.tenant_id
        ):
            raise HTTPException(status_code=404, detail="Target not found")
        self._check_version(target.version, payload.expected_version)

        # Apply non-None fields from payload, preserving existing for None.
        previous = target.to_redacted_dict()
        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None and field != "expected_version":
                setattr(target, field, value)

        # If type changed, recompute default comparison.
        if "target_type" in update_data and update_data["target_type"] is not None:
            target.comparison_operator = target.comparison_operator or _default_comparison(target.target_type)

        await self._validate_target_payload(
            ProjectMetricTargetCreate.model_validate(
                {
                    "target_type": target.target_type,
                    "target_value": target.target_value,
                    "lower_bound": target.lower_bound,
                    "upper_bound": target.upper_bound,
                    "comparison_operator": target.comparison_operator,
                    "warning_threshold": target.warning_threshold,
                    "critical_threshold": target.critical_threshold,
                    "baseline": target.baseline,
                    "effective_start": target.effective_start,
                    "effective_end": target.effective_end,
                    "period": target.period,
                    "notes": target.notes,
                    "status": target.status,
                }
            )
        )

        target.version += 1
        await self.session.flush()
        await self.session.refresh(target)
        invalidate_project_ai_context(self.context.tenant_id, project_id)
        await self._mark_knowledge_graph_stale(project_id, "Project context updated")
        await self._audit(
            project_id=project_id,
            event_type="project_context.target_updated"
            if target.active
            else "project_context.target_archived",
            entity_type="target",
            entity_id=target.id,
            previous_value=previous,
            new_value=target.to_redacted_dict(),
            version=target.version,
        )
        return target

    async def delete_target(self, project_id: int, metric_id: int, target_id: int) -> None:
        await self._require_project(project_id, write=True)
        await self.get_metric(project_id, metric_id)
        target = await self.session.get(ProjectMetricTarget, target_id)
        if (
            target is None
            or target.metric_id != metric_id
            or target.project_id != project_id
            or target.tenant_id != self.context.tenant_id
        ):
            raise HTTPException(status_code=404, detail="Target not found")
        previous = target.to_redacted_dict()
        target.active = False
        target.version += 1
        await self.session.flush()
        invalidate_project_ai_context(self.context.tenant_id, project_id)
        await self._mark_knowledge_graph_stale(project_id, "Project context updated")
        await self._audit(
            project_id=project_id,
            event_type="project_context.target_archived",
            entity_type="target",
            entity_id=target.id,
            previous_value=previous,
            new_value={"active": False},
            version=target.version,
        )

    # ── Risks ────────────────────────────────────────────────────────────

    async def list_risks(self, project_id: int) -> list[ProjectRisk]:
        await self._require_project(project_id)
        result = await self.session.scalars(
            select(ProjectRisk)
            .options(
                selectinload(ProjectRisk.goal_links),
                selectinload(ProjectRisk.metric_links),
            )
            .where(
                ProjectRisk.tenant_id == self.context.tenant_id,
                ProjectRisk.project_id == project_id,
                ProjectRisk.active.is_(True),
            )
            .order_by(ProjectRisk.position)
        )
        return [r for r in result]

    async def _validate_risk_payload(self, payload: ProjectRiskCreate | ProjectRiskUpdate) -> None:
        if hasattr(payload, "likelihood") and payload.likelihood is not None:
            if payload.likelihood not in _VALID_LIKELIHOOD:
                raise HTTPException(status_code=400, detail=f"Invalid likelihood: {payload.likelihood}")
        if hasattr(payload, "impact") and payload.impact is not None:
            if payload.impact not in _VALID_IMPACT:
                raise HTTPException(status_code=400, detail=f"Invalid impact: {payload.impact}")
        if getattr(payload, "severity", None) is not None:
            raise HTTPException(
                status_code=400,
                detail="severity is computed by the server from likelihood and impact "
                "and cannot be set directly.",
            )
        if hasattr(payload, "status") and payload.status is not None:
            if payload.status not in _VALID_RISK_STATUSES:
                raise HTTPException(status_code=400, detail=f"Invalid risk status: {payload.status}")
        await self._validate_owner(payload.owner_id if hasattr(payload, "owner_id") else None)

    async def _sync_risk_links(
        self, risk: ProjectRisk, goal_ids: list[int] | None, metric_ids: list[int] | None
    ) -> None:
        if goal_ids is not None:
            await self._validate_link_ids(goal_ids, ProjectGoal)
            await self.session.execute(
                delete(ProjectGoalRiskLink).where(
                    ProjectGoalRiskLink.risk_id == risk.id
                )
            )
            for gid in set(goal_ids):
                self.session.add(
                    ProjectGoalRiskLink(goal_id=gid, risk_id=risk.id)
                )
        if metric_ids is not None:
            await self._validate_link_ids(metric_ids, ProjectMetric)
            await self.session.execute(
                delete(ProjectRiskMetricLink).where(
                    ProjectRiskMetricLink.risk_id == risk.id
                )
            )
            for mid in set(metric_ids):
                self.session.add(
                    ProjectRiskMetricLink(risk_id=risk.id, metric_id=mid)
                )

    async def create_risk(self, project_id: int, payload: ProjectRiskCreate) -> ProjectRisk:
        await self._require_project(project_id, write=True)
        await self._validate_risk_payload(payload)

        max_position = (
            await self.session.scalar(
                select(ProjectRisk.position)
                .where(ProjectRisk.project_id == project_id)
                .order_by(ProjectRisk.position.desc())
                .limit(1)
            )
            or 0
        )

        risk = ProjectRisk(
            tenant_id=self.context.tenant_id,
            project_id=project_id,
            title=payload.title,
            description=payload.description,
            category=payload.category,
            likelihood=payload.likelihood,
            impact=payload.impact,
            severity=compute_severity(payload.likelihood, payload.impact),
            rating_matrix_version=RATING_MATRIX_VERSION,
            owner_id=payload.owner_id,
            mitigation=payload.mitigation,
            contingency=payload.contingency,
            status=payload.status,
            review_date=payload.review_date,
            source_reference=payload.source_reference,
            position=max_position + 1,
        )
        self.session.add(risk)
        await self.session.flush()
        await self._sync_risk_links(risk, payload.linked_goal_ids, payload.linked_metric_ids)
        await self.session.flush()
        invalidate_project_ai_context(self.context.tenant_id, project_id)
        await self._mark_knowledge_graph_stale(project_id, "Project context updated")

        await self._audit(
            project_id=project_id,
            event_type="project_context.risk_created",
            entity_type="risk",
            entity_id=risk.id,
            new_value=risk.to_redacted_dict(),
            version=risk.version,
        )
        return await self.get_risk(project_id, risk.id)

    async def get_risk(self, project_id: int, risk_id: int) -> ProjectRisk:
        await self._require_project(project_id)
        risk = await self.session.scalar(
            select(ProjectRisk)
            .options(
                selectinload(ProjectRisk.goal_links),
                selectinload(ProjectRisk.metric_links),
            )
            .where(
                ProjectRisk.id == risk_id,
                ProjectRisk.tenant_id == self.context.tenant_id,
            )
        )
        if risk is None or risk.project_id != project_id or risk.tenant_id != self.context.tenant_id:
            raise HTTPException(status_code=404, detail="Risk not found")
        return risk

    async def update_risk(
        self, project_id: int, risk_id: int, payload: ProjectRiskUpdate
    ) -> ProjectRisk:
        await self._require_project(project_id, write=True)
        risk = await self.get_risk(project_id, risk_id)
        self._check_version(risk.version, payload.expected_version)
        await self._validate_risk_payload(payload)

        previous = risk.to_redacted_dict()

        for field in (
            "title",
            "description",
            "category",
            "likelihood",
            "impact",
            "owner_id",
            "mitigation",
            "contingency",
            "status",
            "review_date",
            "source_reference",
            "active",
        ):
            value = getattr(payload, field)
            if value is not None:
                setattr(risk, field, value)

        if payload.likelihood is not None or payload.impact is not None:
            risk.severity = compute_severity(risk.likelihood, risk.impact)
            risk.rating_matrix_version = RATING_MATRIX_VERSION

        risk.version += 1
        if payload.linked_goal_ids is not None or payload.linked_metric_ids is not None:
            await self._sync_risk_links(
                risk,
                payload.linked_goal_ids if payload.linked_goal_ids is not None else None,
                payload.linked_metric_ids if payload.linked_metric_ids is not None else None,
            )

        await self.session.flush()
        invalidate_project_ai_context(self.context.tenant_id, project_id)
        await self._mark_knowledge_graph_stale(project_id, "Project context updated")
        await self._audit(
            project_id=project_id,
            event_type="project_context.risk_updated"
            if risk.active
            else "project_context.risk_archived",
            entity_type="risk",
            entity_id=risk.id,
            previous_value=previous,
            new_value=risk.to_redacted_dict(),
            version=risk.version,
        )
        return await self.get_risk(project_id, risk.id)

    async def delete_risk(self, project_id: int, risk_id: int) -> None:
        await self._require_project(project_id, write=True)
        risk = await self.get_risk(project_id, risk_id)
        previous = risk.to_redacted_dict()
        risk.active = False
        risk.version += 1
        await self.session.flush()
        invalidate_project_ai_context(self.context.tenant_id, project_id)
        await self._mark_knowledge_graph_stale(project_id, "Project context updated")
        await self._audit(
            project_id=project_id,
            event_type="project_context.risk_archived",
            entity_type="risk",
            entity_id=risk.id,
            previous_value=previous,
            new_value={"active": False},
            version=risk.version,
        )

    async def reorder_risks(self, project_id: int, payload: ReorderRequest) -> None:
        await self._require_project(project_id, write=True)
        risks = (
            await self.session.scalars(
                select(ProjectRisk).where(
                    ProjectRisk.tenant_id == self.context.tenant_id,
                    ProjectRisk.project_id == project_id,
                    ProjectRisk.active.is_(True),
                )
            )
        ).all()
        risk_map = {r.id: r for r in risks}
        if set(payload.ids) != set(risk_map):
            raise HTTPException(status_code=400, detail="Reorder ids do not match active risks")
        for idx, risk_id in enumerate(payload.ids):
            risk_map[risk_id].position = idx
            risk_map[risk_id].version += 1
        await self.session.flush()
        invalidate_project_ai_context(self.context.tenant_id, project_id)
        await self._mark_knowledge_graph_stale(project_id, "Project context updated")

    # ── Full context and permissions ────────────────────────────────────

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


def _default_comparison(target_type: str) -> str:
    return {
        "minimum": ">=",
        "increase_by": ">=",
        "maximum": "<=",
        "decrease_by": "<=",
        "exact": "=",
        "range": "between",
    }.get(target_type, ">=")
