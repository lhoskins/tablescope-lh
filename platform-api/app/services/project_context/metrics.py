from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.models.project_context import (
    ProjectGoal,
    ProjectGoalMetricLink,
    ProjectMetric,
)
from app.schemas.project_context import (
    ProjectMetricCreate,
    ProjectMetricUpdate,
    ReorderRequest,
)
from app.services.project_ai_context import invalidate_project_ai_context

from .base import ProjectContextBase
from .core import _VALID_METRIC_AGGREGATION, _VALID_METRIC_DIRECTIONALITY


class MetricsMixin(ProjectContextBase):
    """ProjectContextService mixin."""
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
        self,
        project_id: int,
        name: str,
        success_criterion_id: int | None = None,
        exclude_id: int | None = None,
    ) -> None:
        stmt = select(ProjectMetric).where(
            ProjectMetric.tenant_id == self.context.tenant_id,
            ProjectMetric.project_id == project_id,
            ProjectMetric.active.is_(True),
            ProjectMetric.name == name,
        )
        if success_criterion_id is None:
            stmt = stmt.where(ProjectMetric.success_criterion_id.is_(None))
        else:
            stmt = stmt.where(ProjectMetric.success_criterion_id == success_criterion_id)
        if exclude_id is not None:
            stmt = stmt.where(ProjectMetric.id != exclude_id)
        existing = await self.session.scalar(stmt)
        if existing is not None:
            raise HTTPException(
                status_code=400, detail=f"Metric name '{name}' already exists for this success criterion"
            )


    async def create_metric(self, project_id: int, payload: ProjectMetricCreate) -> ProjectMetric:
        await self._require_project(project_id, write=True)
        await self._validate_metric_payload(payload, project_id=project_id)
        await self._check_metric_name_unique(
            project_id, payload.name, payload.success_criterion_id
        )

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
            await self._check_metric_name_unique(
                project_id,
                payload.name,
                payload.success_criterion_id,
                exclude_id=metric.id,
            )

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


