from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.models.project_context import (
    ProjectGoal,
    ProjectGoalRiskLink,
    ProjectMetric,
    ProjectRisk,
    ProjectRiskMetricLink,
)
from app.schemas.project_context import (
    ProjectRiskCreate,
    ProjectRiskUpdate,
    ReorderRequest,
)
from app.services.project_ai_context import invalidate_project_ai_context
from app.services.risk_rating import RATING_MATRIX_VERSION, compute_severity

from .base import ProjectContextBase
from .core import _VALID_IMPACT, _VALID_LIKELIHOOD, _VALID_RISK_STATUSES


class RisksMixin(ProjectContextBase):
    """ProjectContextService mixin."""
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


