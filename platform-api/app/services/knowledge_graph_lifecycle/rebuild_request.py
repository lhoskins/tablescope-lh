from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from arq.worker import Retry
from sqlalchemy import func, select

from app.config import get_settings
from app.models import (
    AIProjectGraphEdge,
    AIProjectGraphNode,
    KnowledgeGraph,
    KnowledgeGraphBuild,
)

from .base import LifecycleBase
from .state import logger


class RebuildRequestMixin(LifecycleBase):
    """KnowledgeGraphLifecycleManager mixin."""
    def _resolve_requested_by(self, requested_by: int | None) -> int | None:
        """Attribute a build to a user: explicit override, else the request user.

        ``requested_by`` drives AI enrichment in the worker (cards are only
        pre-cached when a user id is present), so headless callers pass an
        explicit representative user (e.g. the project owner).
        """
        if requested_by is not None:
            return requested_by
        return self.context.user_id if self.context else None


    async def request_full_rebuild(
        self,
        project_id: int,
        *,
        trigger: str = "manual",
        requested_by: int | None = None,
    ) -> tuple[KnowledgeGraphBuild, str]:
        """Create a full rebuild build record and return it with the chosen build type.

        Does not enqueue the worker; callers (routes) are responsible for
        queueing so HTTP requests never wait on graph construction.
        """
        await self._require_project(project_id, write=True)
        graph = await self.ensure_graph(project_id, reason="Full rebuild requested")

        duplicate = await self.session.scalar(
            select(KnowledgeGraphBuild).where(
                KnowledgeGraphBuild.project_id == project_id,
                KnowledgeGraphBuild.status.in_(
                    ["queued", "building", "validating"]
                ),
                KnowledgeGraphBuild.build_type == "full",
            )
        )
        if duplicate is not None:
            return duplicate, "full"

        build = KnowledgeGraphBuild(
            graph_id=graph.id,
            tenant_id=graph.tenant_id,
            project_id=project_id,
            trigger_type=trigger,
            build_type="full",
            requested_by=self._resolve_requested_by(requested_by),
            status="queued",
            queued_at=datetime.now(UTC),
            stage="queued",
            progress=0,
        )
        self.session.add(build)
        graph.lifecycle_status = "requested"
        graph.version += 1
        await self.session.flush()

        await self._audit(
            project_id=project_id,
            event_type="knowledge_graph.rebuild_requested",
            title=f"Full rebuild requested ({trigger})",
            prompt_type="full",
        )
        return build, "full"


    async def request_incremental_rebuild(
        self,
        project_id: int,
        *,
        change_set: list[dict[str, Any]],
        trigger: str = "change_event",
        requested_by: int | None = None,
        source_checkpoint: datetime | None = None,
    ) -> tuple[KnowledgeGraphBuild, str]:
        """Analyze the change set and create an incremental (or full fallback) build.

        Rapid successive change events coalesce onto an already-queued build for
        the project instead of stacking duplicates: an incremental run re-reads
        current source state at execution time, so one queued build covers every
        change that lands before it starts.

        KG-41: coalescing used to return the already-queued build completely
        unchanged, discarding this call's own change set -- ``_patch_context_nodes``
        only patches the types named in ``affected_entity_summary``, so an event
        that arrived after the first (e.g. a risk created while a document-change
        build was still queued) was silently dropped from the eventual incremental
        patch. The new event's impact is now unioned into the pending build, and
        the build escalates to a full rebuild if this event alone isn't safely
        incremental, even when the original queued build was.
        """
        await self._require_project(project_id, write=True)
        graph = await self.ensure_graph(project_id, reason="Incremental rebuild requested")

        pending = await self.session.scalar(
            select(KnowledgeGraphBuild)
            .where(
                KnowledgeGraphBuild.project_id == project_id,
                KnowledgeGraphBuild.status == "queued",
            )
            .order_by(KnowledgeGraphBuild.id.desc())
        )
        analysis = await self.impact_analyzer.analyze(change_set, current_graph=graph)

        if pending is not None:
            self._coalesce_change_set(pending, analysis, source_checkpoint)
            await self.session.flush()
            return pending, pending.build_type

        build_type = "full" if not analysis["safe_incremental"] else "incremental"

        checkpoint_value: dict[str, Any] = {"analysis": analysis}
        if source_checkpoint is not None:
            checkpoint_value["timestamp"] = source_checkpoint.isoformat()

        build = KnowledgeGraphBuild(
            graph_id=graph.id,
            tenant_id=graph.tenant_id,
            project_id=project_id,
            trigger_type=trigger,
            build_type=build_type,
            requested_by=self._resolve_requested_by(requested_by),
            status="queued",
            queued_at=datetime.now(UTC),
            stage="queued",
            progress=0,
            source_checkpoint=checkpoint_value,
            affected_entity_summary={
                "affected_types": analysis["affected_entity_types"],
                "affected_ids": analysis["affected_entity_ids"],
                "fallback_reason": analysis.get("fallback_reason"),
            },
        )
        self.session.add(build)
        graph.lifecycle_status = "requested"
        graph.version += 1
        await self.session.flush()

        await self._audit(
            project_id=project_id,
            event_type="knowledge_graph.incremental_rebuild_requested",
            title=f"Incremental rebuild requested ({trigger})",
            prompt_type=build_type,
        )
        return build, build_type


    def _coalesce_change_set(
        self,
        pending: KnowledgeGraphBuild,
        analysis: dict[str, Any],
        source_checkpoint: datetime | None,
    ) -> None:
        """KG-41: fold a new change event's impact into an already-queued build.

        Unions the new event's affected types/ids into ``affected_entity_summary``
        (deduped, order-preserving), advances the source checkpoint used to defer
        the job until the newest write is visible, and escalates the queued
        build to ``full`` if this event alone requires it -- a build already
        queued as incremental must not silently stay incremental once a later,
        unsafe change has been folded into it.
        """
        summary = dict(pending.affected_entity_summary or {})
        merged_types = list(summary.get("affected_types") or [])
        for t in analysis["affected_entity_types"]:
            if t not in merged_types:
                merged_types.append(t)
        merged_ids = list(summary.get("affected_ids") or [])
        for i in analysis["affected_entity_ids"]:
            if i not in merged_ids:
                merged_ids.append(i)
        summary["affected_types"] = merged_types
        summary["affected_ids"] = merged_ids
        if not analysis["safe_incremental"]:
            summary["fallback_reason"] = analysis.get("fallback_reason")
        pending.affected_entity_summary = summary

        if not analysis["safe_incremental"] and pending.build_type == "incremental":
            pending.build_type = "full"

        checkpoint = dict(pending.source_checkpoint or {})
        checkpoint["analysis"] = analysis
        if source_checkpoint is not None:
            existing_ts = checkpoint.get("timestamp")
            new_ts = source_checkpoint.isoformat()
            if not existing_ts or new_ts > str(existing_ts):
                checkpoint["timestamp"] = new_ts
        pending.source_checkpoint = checkpoint


    def evaluate_rebuild_type(
        self,
        change_set: list[dict[str, Any]],
        *,
        current_graph: KnowledgeGraph | None = None,
    ) -> dict[str, Any]:
        """Synchronous helper; most callers should use ``request_incremental_rebuild``."""
        return asyncio.run(
            self.impact_analyzer.analyze(change_set, current_graph=current_graph)
        )


    async def _snapshot_storage_key(
        self, project_id: int, version_number: int
    ) -> str:
        return f"kg_v_{project_id}_{version_number}"


    async def _verify_source_checkpoint(self, build: KnowledgeGraphBuild) -> None:
        """Ensure the triggering source write is visible before reading graph rows.

        Document/relationship writes are committed before the rebuild is enqueued,
        but replica lag or an early coalesced build can still read a stale view.
        If the most-recent ``created_at`` on the staging node/edge tables is
        older than the caller's checkpoint, defer the job so arq retries.
        """
        if not build.source_checkpoint:
            return
        timestamp = build.source_checkpoint.get("timestamp")
        if not timestamp:
            return

        try:
            checkpoint = datetime.fromisoformat(str(timestamp))
        except (TypeError, ValueError):
            return

        if checkpoint.tzinfo is None:
            checkpoint = checkpoint.replace(tzinfo=UTC)

        node_max = await self.session.scalar(
            select(func.max(AIProjectGraphNode.created_at)).where(
                AIProjectGraphNode.tenant_id == build.tenant_id,
                AIProjectGraphNode.project_id == build.project_id,
            )
        )
        edge_max = await self.session.scalar(
            select(func.max(AIProjectGraphEdge.created_at)).where(
                AIProjectGraphEdge.tenant_id == build.tenant_id,
                AIProjectGraphEdge.project_id == build.project_id,
            )
        )

        if node_max is not None and node_max.tzinfo is None:
            node_max = node_max.replace(tzinfo=UTC)
        if edge_max is not None and edge_max.tzinfo is None:
            edge_max = edge_max.replace(tzinfo=UTC)

        max_ts = node_max or edge_max
        if node_max and edge_max:
            max_ts = max(node_max, edge_max)

        if max_ts is None or max_ts < checkpoint:
            logger.info(
                "KG build %s source checkpoint not yet visible (max=%s checkpoint=%s); deferring",
                build.id,
                max_ts,
                checkpoint,
            )
            raise Retry(
                defer=get_settings().home_intelligence_tenant_slot_retry_seconds
            )


