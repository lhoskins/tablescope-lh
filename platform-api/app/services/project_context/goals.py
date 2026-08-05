from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.models.project_context import (
    ProjectGoal,
    ProjectGoalMetricLink,
    ProjectGoalRiskLink,
    ProjectMetric,
    ProjectRisk,
)
from app.schemas.project_context import (
    ProjectGoalCreate,
    ProjectGoalUpdate,
    ReorderRequest,
)
from app.services.project_ai_context import invalidate_project_ai_context

from .base import ProjectContextBase
from .core import _VALID_GOAL_STATUSES, _VALID_PRIORITIES


class GoalsMixin(ProjectContextBase):
    """ProjectContextService mixin."""
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


