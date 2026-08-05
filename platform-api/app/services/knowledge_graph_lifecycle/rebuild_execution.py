from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from arq.worker import Retry
from sqlalchemy import select

from app.models import (
    AIProjectGraphSnapshot,
    KnowledgeGraph,
    KnowledgeGraphBuild,
    KnowledgeGraphVersion,
    ProjectGoal,
    ProjectMetric,
    ProjectRisk,
)
from app.services.knowledge_graph_builder import (
    SNAPSHOT_PIPELINE_VERSION,
    _json_safe,
    _load_stored_graph,
    _precache_center_cards,
    _snapshot_source_counts,
)

from .base import LifecycleBase
from .state import logger


class RebuildExecutionMixin(LifecycleBase):
    """KnowledgeGraphLifecycleManager mixin."""
    async def run_full_rebuild(self, build_id: int) -> None:
        """Execute a full rebuild: build candidate, validate, activate, or preserve."""
        build = await self.session.get(KnowledgeGraphBuild, build_id)
        if build is None:
            logger.error("Knowledge graph build %s not found", build_id)
            return

        graph = await self.session.get(KnowledgeGraph, build.graph_id)
        if graph is None:
            graph = await self.ensure_graph(build.project_id)

        await self._transition_build(
            build, status="building", stage="initializing", progress=5
        )
        graph.lifecycle_status = "building"

        await self._verify_source_checkpoint(build)

        try:
            fingerprint = await self.compute_source_fingerprint(build.project_id)
            await self._transition_build(
                build, stage="fingerprinting", progress=15
            )

            # Build payload from the stored graph (nodes/edges + structural evidence).
            raw_nodes, raw_edges = await _load_stored_graph(
                self.session,
                tenant_id=build.tenant_id,
                project_id=build.project_id,
            )
            await self._transition_build(build, stage="loading_sources", progress=35)

            user_id = build.requested_by
            ai_cards: dict[str, Any] = {}
            if user_id is not None:
                try:
                    ai_cards = await _precache_center_cards(
                        raw_nodes,
                        raw_edges,
                        tenant_id=build.tenant_id,
                        user_id=user_id,
                        project_id=build.project_id,
                    )
                except Exception:
                    logger.exception("AI precache failed for build %s; continuing", build.id)
            await self._transition_build(build, stage="ai_enrichment", progress=60)

            generated_at = datetime.now(UTC).isoformat()
            payload = _json_safe({
                "fullGraph": {"nodes": raw_nodes, "edges": raw_edges},
                "sourceCounts": _snapshot_source_counts(raw_nodes),
                "aiCardsByCenter": ai_cards,
                "pipelineVersion": SNAPSHOT_PIPELINE_VERSION,
                "generatedAt": generated_at,
                "sourceFingerprint": fingerprint,
            })

            version_number = await self._next_version_number(build.project_id)
            version = KnowledgeGraphVersion(
                graph_id=graph.id,
                tenant_id=build.tenant_id,
                project_id=build.project_id,
                version_number=version_number,
                build_id=build.id,
                status="candidate",
                build_type="full",
                source_fingerprint=fingerprint,
                node_count=len(raw_nodes),
                edge_count=len(raw_edges),
                created_by=build.requested_by,
            )
            self.session.add(version)
            await self.session.flush()

            storage_key = await self._snapshot_storage_key(build.project_id, version_number)
            snapshot = AIProjectGraphSnapshot(
                tenant_id=build.tenant_id,
                project_id=build.project_id,
                snapshot_key=storage_key,
                payload=payload,
                pipeline_version=SNAPSHOT_PIPELINE_VERSION,
                generated_at=datetime.now(UTC),
                created_by=build.requested_by,
            )
            self.session.add(snapshot)
            version.storage_reference = storage_key
            await self.session.flush()

            await self._transition_build(
                build, status="validating", stage="validating", progress=80
            )

            validation = self._validate_payload(payload, version)
            version.validation_summary = validation
            version.disconnected_component_count = validation.get(
                "disconnected_components", 0
            )

            if not validation["valid"]:
                await self._fail_build(
                    build,
                    error_code="validation_failed",
                    message=validation.get("summary", "Candidate validation failed"),
                )
                graph.lifecycle_status = "failed"
                await self._audit(
                    project_id=build.project_id,
                    event_type="knowledge_graph.build_failed",
                    title="Full rebuild validation failed",
                    prompt_type="full",
                )
                return

            version.status = "ready"
            await self._transition_build(
                build, status="succeeded", stage="activating", progress=95
            )

            await self.activate_version(graph.id, version.id)
            await self._transition_build(build, stage="completed", progress=100)

            graph.current_source_fingerprint = fingerprint
            graph.last_successful_build_at = datetime.now(UTC)
            graph.lifecycle_status = "active"

            await self._audit(
                project_id=build.project_id,
                event_type="knowledge_graph.build_succeeded",
                title="Full rebuild succeeded",
                prompt_type="full",
            )

        except Retry:
            raise
        except Exception as exc:
            logger.exception("Full rebuild failed for build %s", build_id)
            await self._fail_build(
                build,
                error_code="build_exception",
                message=str(exc)[:500],
            )
            graph.lifecycle_status = "failed"
            await self._audit(
                project_id=build.project_id,
                event_type="knowledge_graph.build_failed",
                title="Full rebuild failed",
                prompt_type="full",
            )


    async def run_incremental_rebuild(self, build_id: int) -> None:
        """Execute an incremental rebuild, falling back to full if validation fails."""
        build = await self.session.get(KnowledgeGraphBuild, build_id)
        if build is None:
            return
        if build.build_type != "incremental":
            # Something scheduled the wrong runner; defer to full rebuild logic.
            await self.run_full_rebuild(build_id)
            return

        graph = await self.session.get(KnowledgeGraph, build.graph_id)
        if graph is None:
            graph = await self.ensure_graph(build.project_id)

        await self._transition_build(
            build, status="building", stage="initializing", progress=5
        )
        graph.lifecycle_status = "building"

        await self._verify_source_checkpoint(build)

        try:
            active_version = await self._load_version(graph.active_version_id or 0)
            if active_version is None or not active_version.storage_reference:
                # No active version to patch; fall back to a full rebuild.
                build.build_type = "full"
                build.source_checkpoint = {
                    **(build.source_checkpoint or {}),
                    "fallback_reason": "No active version for incremental patch",
                }
                await self.run_full_rebuild(build_id)
                return

            fingerprint = await self.compute_source_fingerprint(build.project_id)
            active_snapshot = await self.session.scalar(
                select(AIProjectGraphSnapshot).where(
                    AIProjectGraphSnapshot.tenant_id == build.tenant_id,
                    AIProjectGraphSnapshot.project_id == build.project_id,
                    AIProjectGraphSnapshot.snapshot_key == active_version.storage_reference,
                )
            )
            if active_snapshot is None:
                build.build_type = "full"
                await self.run_full_rebuild(build_id)
                return

            payload = _json_safe(active_snapshot.payload)
            affected = build.affected_entity_summary or {}
            affected_types = affected.get("affected_types", [])
            affected_ids = affected.get("affected_ids", [])

            # Reload the stored graph rows plus the structural Evidence graph so
            # content changes (new/updated documents, data sources, queries) are
            # reflected in the new version. The expensive part of a full rebuild
            # is AI enrichment, which stays cached: ``aiCardsByCenter`` carries
            # over from the active snapshot unchanged.
            fresh_nodes, fresh_edges = await _load_stored_graph(
                self.session,
                tenant_id=build.tenant_id,
                project_id=build.project_id,
            )
            payload["fullGraph"] = _json_safe(
                {"nodes": fresh_nodes, "edges": fresh_edges}
            )

            # Patch the payload for affected project-context entities.
            if "goal" in affected_types or "metric" in affected_types or "risk" in affected_types:
                await self._patch_context_nodes(
                    payload,
                    build.project_id,
                    affected_types,
                    affected_ids,
                )

            await self._transition_build(build, stage="patching_sources", progress=50)

            # Re-run source counts and fingerprint.
            raw_nodes = payload.get("fullGraph", {}).get("nodes", [])
            raw_edges = payload.get("fullGraph", {}).get("edges", [])
            payload["sourceCounts"] = _snapshot_source_counts(raw_nodes)
            payload["sourceFingerprint"] = fingerprint
            payload["generatedAt"] = datetime.now(UTC).isoformat()
            payload["pipelineVersion"] = SNAPSHOT_PIPELINE_VERSION

            version_number = await self._next_version_number(build.project_id)
            version = KnowledgeGraphVersion(
                graph_id=graph.id,
                tenant_id=build.tenant_id,
                project_id=build.project_id,
                version_number=version_number,
                build_id=build.id,
                status="candidate",
                build_type="incremental",
                source_fingerprint=fingerprint,
                node_count=len(raw_nodes),
                edge_count=len(raw_edges),
                created_by=build.requested_by,
            )
            self.session.add(version)
            await self.session.flush()

            storage_key = await self._snapshot_storage_key(build.project_id, version_number)
            snapshot = AIProjectGraphSnapshot(
                tenant_id=build.tenant_id,
                project_id=build.project_id,
                snapshot_key=storage_key,
                payload=payload,
                pipeline_version=SNAPSHOT_PIPELINE_VERSION,
                generated_at=datetime.now(UTC),
                created_by=build.requested_by,
            )
            self.session.add(snapshot)
            version.storage_reference = storage_key
            await self.session.flush()

            validation = self._validate_payload(payload, version)
            version.validation_summary = validation
            version.disconnected_component_count = validation.get(
                "disconnected_components", 0
            )

            if not validation["valid"]:
                # Fallback to full rebuild on validation failure.
                build.build_type = "full"
                build.source_checkpoint = {
                    **(build.source_checkpoint or {}),
                    "fallback_reason": validation.get("summary", "Incremental validation failed"),
                }
                await self.run_full_rebuild(build_id)
                return

            version.status = "ready"
            await self.activate_version(graph.id, version.id)
            await self._transition_build(
                build, status="succeeded", stage="completed", progress=100
            )

            graph.current_source_fingerprint = fingerprint
            graph.last_successful_build_at = datetime.now(UTC)
            graph.lifecycle_status = "active"

            await self._audit(
                project_id=build.project_id,
                event_type="knowledge_graph.build_succeeded",
                title="Incremental rebuild succeeded",
                prompt_type="incremental",
            )

        except Retry:
            raise
        except Exception as exc:
            logger.exception("Incremental rebuild failed for build %s", build_id)
            # Fall back to a full rebuild once on unexpected errors.
            build.build_type = "full"
            build.source_checkpoint = {
                **(build.source_checkpoint or {}),
                "fallback_reason": str(exc)[:500],
            }
            await self.run_full_rebuild(build_id)


    async def _patch_context_nodes(
        self,
        payload: dict[str, Any],
        project_id: int,
        affected_types: list[str],
        affected_ids: list[int | None],
    ) -> None:
        """Patch project-context synthetic nodes into the existing payload."""
        nodes: list[dict[str, Any]] = payload.setdefault("fullGraph", {}).setdefault("nodes", [])
        node_map = {n.get("id"): n for n in nodes if n.get("id") is not None}

        if "goal" in affected_types:
            goals = (
                await self.session.scalars(
                    select(ProjectGoal).where(
                        ProjectGoal.project_id == project_id,
                        ProjectGoal.active.is_(True),
                    )
                )
            ).all()
            for goal in goals:
                key = f"goal:{goal.id}"
                node = {
                    "id": key,
                    "node_type": "goal",
                    "name": goal.title,
                    "source_type": "project_context",
                    "source_id": goal.id,
                    "properties": {
                        "priority": goal.priority,
                        "status": goal.status,
                        "category": goal.category,
                    },
                }
                node_map[key] = node

        if "metric" in affected_types:
            metrics = (
                await self.session.scalars(
                    select(ProjectMetric).where(
                        ProjectMetric.project_id == project_id,
                        ProjectMetric.active.is_(True),
                    )
                )
            ).all()
            for metric in metrics:
                key = f"metric:{metric.id}"
                node = {
                    "id": key,
                    "node_type": "metric",
                    "name": metric.name,
                    "source_type": "project_context",
                    "source_id": metric.id,
                    "properties": {
                        "aggregation": metric.aggregation,
                        "directionality": metric.directionality,
                        "unit": metric.unit,
                    },
                }
                node_map[key] = node

        if "risk" in affected_types:
            risks = (
                await self.session.scalars(
                    select(ProjectRisk).where(
                        ProjectRisk.project_id == project_id,
                        ProjectRisk.active.is_(True),
                    )
                )
            ).all()
            for risk in risks:
                key = f"risk:{risk.id}"
                node = {
                    "id": key,
                    "node_type": "risk",
                    "name": risk.title,
                    "source_type": "project_context",
                    "source_id": risk.id,
                    "properties": {
                        "likelihood": risk.likelihood,
                        "impact": risk.impact,
                        "severity": risk.severity,
                    },
                }
                node_map[key] = node

        payload["fullGraph"]["nodes"] = list(node_map.values())


    def _validate_payload(
        self, payload: dict[str, Any], version: KnowledgeGraphVersion
    ) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []

        full_graph = payload.get("fullGraph") or {}
        nodes = full_graph.get("nodes") or []
        edges = full_graph.get("edges") or []

        if not nodes:
            errors.append("Graph contains no nodes")

        project_nodes = [n for n in nodes if n.get("node_type") == "project"]
        if len(project_nodes) != 1:
            warnings.append(f"Expected exactly one project node, found {len(project_nodes)}")

        source_counts = payload.get("sourceCounts") or {}
        if not source_counts:
            warnings.append("No source counts in payload")

        # Very simple connectivity check: count orphan-ish nodes with no edge refs.
        node_ids = {n.get("id") for n in nodes if n.get("id")}
        edge_refs = set()
        for e in edges:
            edge_refs.add(e.get("from_node_id"))
            edge_refs.add(e.get("to_node_id"))
        orphan_ids = node_ids - edge_refs - {"project"}
        orphan_ratio = (len(orphan_ids) / len(nodes)) if nodes else 0.0

        if orphan_ratio > 0.5:
            warnings.append(f"High orphan ratio: {orphan_ratio:.2%}")

        disconnected = version.disconnected_component_count or 0

        return {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "orphan_ratio": orphan_ratio,
            "disconnected_components": disconnected,
            "summary": "; ".join(errors) if errors else "Candidate graph is valid",
        }


    async def _transition_build(
        self,
        build: KnowledgeGraphBuild,
        *,
        status: str | None = None,
        stage: str | None = None,
        progress: int | None = None,
    ) -> None:
        if status:
            build.status = status
            if status in ("succeeded", "failed", "cancelled"):
                build.completed_at = datetime.now(UTC)
            if status == "building" and build.started_at is None:
                build.started_at = datetime.now(UTC)
        if stage:
            build.stage = stage
        if progress is not None:
            build.progress = max(0, min(100, progress))
        build.heartbeat_at = datetime.now(UTC)
        await self.session.flush()


    async def _fail_build(
        self,
        build: KnowledgeGraphBuild,
        *,
        error_code: str,
        message: str,
    ) -> None:
        build.status = "failed"
        build.error_code = error_code
        build.safe_error_message = message
        build.completed_at = datetime.now(UTC)
        build.heartbeat_at = datetime.now(UTC)


