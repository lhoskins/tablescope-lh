from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select

from app.models.project_context import (
    ProjectMetric,
    ProjectMetricTarget,
)
from app.schemas.project_context import (
    ProjectMetricTargetCreate,
    ProjectMetricTargetUpdate,
)
from app.services.project_ai_context import invalidate_project_ai_context

from .base import ProjectContextBase
from .core import _VALID_TARGET_STATUSES, _VALID_TARGET_TYPES


def _default_comparison(target_type: str) -> str:
    return {
        "minimum": ">=",
        "increase_by": ">=",
        "maximum": "<=",
        "decrease_by": "<=",
        "exact": "=",
        "range": "between",
    }.get(target_type, ">=")


class TargetsMixin(ProjectContextBase):
    """ProjectContextService mixin."""
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


