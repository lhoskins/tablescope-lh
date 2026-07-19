"""Knowledge graph lifecycle manager, rebuild orchestration, and source fingerprinting."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, has_role
from app.models import (
    AIProjectGraphSnapshot,
    AuditEvent,
    Dashboard,
    DatabaseDataSource,
    KnowledgeGraph,
    KnowledgeGraphBuild,
    KnowledgeGraphHealthCheck,
    KnowledgeGraphVersion,
    Project,
    ProjectAsset,
    ProjectBusinessContext,
    ProjectGoal,
    ProjectMember,
    ProjectMetric,
    ProjectRisk,
    RepositoryConnection,
    RepositoryScan,
    SavedQuery,
)
from app.services.knowledge_graph_builder import (
    SNAPSHOT_PIPELINE_VERSION,
    _json_safe,
    _load_stored_graph,
    _precache_center_cards,
    _snapshot_source_counts,
)

logger = logging.getLogger(__name__)

MAX_INCREMENTAL_AFFECTED = 50
MAX_VERSION_HISTORY = 20
BUILD_HEARTBEAT_TIMEOUT_SECONDS = 300


class KnowledgeGraphConcurrencyError(HTTPException):
    """Raised when an optimistic lock on the graph row fails."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail="Knowledge graph state changed during the operation; retry.",
        )


class _ChangeSet:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items

    def has(self, scope: str) -> bool:
        return any(item.get("change_scope") == scope for item in self.items)

    def entity_types(self) -> set[str]:
        return {str(item.get("entity_type") or "unknown") for item in self.items}

    def count(self) -> int:
        return len(self.items)


class GraphImpactAnalyzer:
    """Decide whether a source change set can be handled incrementally."""

    async def analyze(
        self,
        change_set: list[dict[str, Any]],
        *,
        current_graph: KnowledgeGraph | None = None,
    ) -> dict[str, Any]:
        changes = _ChangeSet(change_set)

        if not change_set:
            return {
                "scope": "none",
                "safe_incremental": False,
                "fallback_reason": "Empty change set",
                "affected_entity_types": [],
                "affected_entity_ids": [],
            }

        if changes.has("schema"):
            return {
                "scope": "full",
                "safe_incremental": False,
                "fallback_reason": "Schema-level source changes require a full rebuild",
                "affected_entity_types": sorted(changes.entity_types()),
                "affected_entity_ids": [],
            }

        structural_types = {"data_source", "saved_query", "dashboard", "repository_connection"}
        if changes.entity_types() & structural_types:
            # A structural source change is allowed to be incremental if the
            # number of affected entities is small; otherwise fall back to full.
            if changes.count() > MAX_INCREMENTAL_AFFECTED:
                return {
                    "scope": "full",
                    "safe_incremental": False,
                    "fallback_reason": f"Too many structural source changes ({changes.count()} > {MAX_INCREMENTAL_AFFECTED})",
                    "affected_entity_types": sorted(changes.entity_types()),
                    "affected_entity_ids": [],
                }

        if changes.count() > MAX_INCREMENTAL_AFFECTED:
            return {
                "scope": "full",
                "safe_incremental": False,
                "fallback_reason": f"Too many entity changes ({changes.count()} > {MAX_INCREMENTAL_AFFECTED})",
                "affected_entity_types": sorted(changes.entity_types()),
                "affected_entity_ids": [],
            }

        if current_graph is not None and current_graph.lifecycle_status in (
            "failed",
            "missing",
            "degraded",
        ):
            return {
                "scope": "full",
                "safe_incremental": False,
                "fallback_reason": f"Current graph status is {current_graph.lifecycle_status}; a full rebuild is safer",
                "affected_entity_types": sorted(changes.entity_types()),
                "affected_entity_ids": [],
            }

        return {
            "scope": "incremental",
            "safe_incremental": True,
            "fallback_reason": None,
            "affected_entity_types": sorted(changes.entity_types()),
            "affected_entity_ids": [
                item.get("entity_id")
                for item in change_set
                if item.get("entity_id") is not None
            ],
        }


class KnowledgeGraphLifecycleManager:
    """Central lifecycle orchestrator for project knowledge graphs.

    Responsibilities:
    - Ensure a ``KnowledgeGraph`` row exists per project.
    - Queue and track full/incremental rebuilds.
    - Build candidate versions, validate them, and atomically activate them.
    - Preserve the last healthy version when activation fails.
    - Prevent duplicate rebuild jobs and mark stale source fingerprints.
    """

    def __init__(
        self,
        session: AsyncSession,
        context: RequestContext | None = None,
    ) -> None:
        self.session = session
        self.context = context
        self.impact_analyzer = GraphImpactAnalyzer()

    # ── Access control ──────────────────────────────────────────────────────

    async def _require_project(
        self, project_id: int, *, write: bool = False
    ) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
            )
        tenant_id = self.context.tenant_id if self.context else project.tenant_id
        if project.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
            )

        if not write:
            return project

        # No request context means a system-initiated call (worker task, event
        # trigger). Those are already tenant-scoped above and carry no user to
        # authorize, so they are allowed to schedule rebuilds.
        if self.context is None:
            return project

        user_id = self.context.user_id if self.context else None
        role = self.context.role if self.context else None
        if project.owner_id == user_id or has_role(role or "", Role.ADMIN):
            return project
        member = await self.session.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
                ProjectMember.is_active.is_(True),
            )
        )
        if member is not None and member.role in ("editor", "admin", "owner"):
            return project
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No access to this project"
        )

    # ── Graph row / version helpers ─────────────────────────────────────────

    async def ensure_graph(
        self,
        project_id: int,
        *,
        reason: str | None = None,
    ) -> KnowledgeGraph:
        """Return the project's ``KnowledgeGraph`` row, creating it lazily."""
        project = await self._require_project(project_id)
        graph = await self.session.scalar(
            select(KnowledgeGraph).where(
                KnowledgeGraph.tenant_id == project.tenant_id,
                KnowledgeGraph.project_id == project_id,
            )
        )
        if graph is None:
            graph = KnowledgeGraph(
                tenant_id=project.tenant_id,
                project_id=project_id,
                lifecycle_status="missing",
                enabled=True,
                version=0,
            )
            self.session.add(graph)
            await self.session.flush()
            await self._audit(
                project_id=project_id,
                event_type="knowledge_graph.ensure_graph",
                title=reason or "Graph row initialized",
            )
        return graph

    async def _next_version_number(self, project_id: int) -> int:
        result = await self.session.scalar(
            select(func.coalesce(func.max(KnowledgeGraphVersion.version_number), 0)).where(
                KnowledgeGraphVersion.project_id == project_id
            )
        )
        return int(result or 0) + 1

    async def _load_version(self, version_id: int) -> KnowledgeGraphVersion | None:
        return await self.session.get(KnowledgeGraphVersion, version_id)

    # ── Audit ───────────────────────────────────────────────────────────────

    async def _audit(
        self,
        *,
        project_id: int,
        event_type: str,
        title: str | None = None,
        prompt_type: str | None = None,
        tables: list[str] | None = None,
        documents: list[str] | None = None,
    ) -> None:
        tenant_id = self.context.tenant_id if self.context else None
        if tenant_id is None:
            project = await self.session.get(Project, project_id)
            if project:
                tenant_id = project.tenant_id
        if tenant_id is None:
            return
        self.session.add(
            AuditEvent(
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=self.context.user_id if self.context else None,
                event_type=event_type,
                scope="knowledge_graph",
                title=title,
                prompt_type=prompt_type,
                tables_queried=tables or [],
                documents_read=documents or [],
            )
        )

    # ── Source fingerprinting ───────────────────────────────────────────────

    async def compute_source_fingerprint(self, project_id: int) -> str:
        """Compute a deterministic fingerprint of all graph-relevant sources."""
        project = await self.session.get(Project, project_id)
        tenant_id = project.tenant_id if project else 0

        parts: dict[str, Any] = {
            "project_version": 0,
            "goals": [],
            "metrics": [],
            "risks": [],
            "data_sources": [],
            "saved_queries": [],
            "dashboards": [],
            "assets": [],
            "repository_scans": [],
            "pipeline_version": SNAPSHOT_PIPELINE_VERSION,
        }

        settings = await self.session.scalar(
            select(ProjectBusinessContext).where(
                ProjectBusinessContext.tenant_id == tenant_id,
                ProjectBusinessContext.project_id == project_id,
            )
        )
        if settings:
            parts["project_version"] = settings.version

        fingerprint_models: list[tuple[Any, str, str, str]] = [
            (ProjectGoal, "goals", "id", "updated_at"),
            (ProjectMetric, "metrics", "id", "updated_at"),
            (ProjectRisk, "risks", "id", "updated_at"),
            (DatabaseDataSource, "data_sources", "id", "updated_at"),
            (SavedQuery, "saved_queries", "id", "updated_at"),
            (Dashboard, "dashboards", "id", "updated_at"),
            (ProjectAsset, "assets", "id", "updated_at"),
        ]
        for model, key, id_attr, ts_attr in fingerprint_models:
            id_col = getattr(model, id_attr)
            ts_col = getattr(model, ts_attr)
            stmt = select(id_col, ts_col).where(model.project_id == project_id)
            if hasattr(model, "tenant_id"):
                stmt = stmt.where(model.tenant_id == tenant_id)
            rows = (await self.session.execute(stmt)).all()
            parts[key] = sorted(
                [
                    (r[0], r[1].isoformat() if r[1] else None)
                    for r in rows
                ],
                key=lambda x: x[0],
            )

        conn_ids = (
            await self.session.scalars(
                select(RepositoryConnection.id).where(
                    RepositoryConnection.project_id == project_id,
                    RepositoryConnection.tenant_id == tenant_id,
                )
            )
        ).all()
        for conn_id in conn_ids:
            scan = await self.session.scalar(
                select(RepositoryScan)
                .where(RepositoryScan.connection_id == conn_id)
                .order_by(RepositoryScan.id.desc())
            )
            parts["repository_scans"].append(
                (conn_id, scan.id if scan else None, scan.updated_at.isoformat() if scan and scan.updated_at else None)
            )

        serialized = json.dumps(parts, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    # ── Build scheduling ──────────────────────────────────────────────────

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
    ) -> tuple[KnowledgeGraphBuild, str]:
        """Analyze the change set and create an incremental (or full fallback) build.

        Rapid successive change events coalesce onto an already-queued build for
        the project instead of stacking duplicates: an incremental run re-reads
        current source state at execution time, so one queued build covers every
        change that lands before it starts.
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
        if pending is not None:
            return pending, pending.build_type

        analysis = await self.impact_analyzer.analyze(change_set, current_graph=graph)
        build_type = "full" if not analysis["safe_incremental"] else "incremental"

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
            source_checkpoint={"analysis": analysis},
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

    # ── Build execution (called by the worker) ──────────────────────────────

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

    # ── Validation / activation ─────────────────────────────────────────────

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

    async def activate_version(self, graph_id: int, version_id: int) -> KnowledgeGraph:
        """Atomically activate a validated candidate version and supersede the prior active."""
        graph = await self.session.get(KnowledgeGraph, graph_id)
        if graph is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge graph not found"
            )

        version = await self.session.get(KnowledgeGraphVersion, version_id)
        if version is None or version.graph_id != graph_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Version not found"
            )

        previous_active_id = graph.active_version_id
        if previous_active_id:
            prev = await self.session.get(KnowledgeGraphVersion, previous_active_id)
            if prev is not None:
                prev.status = "superseded"
                prev.superseded_at = datetime.now(UTC)

        version.status = "active"
        version.activated_at = datetime.now(UTC)
        graph.active_version_id = version.id
        graph.last_healthy_version_id = version.id
        graph.lifecycle_status = "active"

        await self._audit(
            project_id=graph.project_id,
            event_type="knowledge_graph.version_activated",
            title=f"Activated version {version.version_number}",
            prompt_type=version.build_type,
        )
        return graph

    async def mark_stale(self, project_id: int, reason: str) -> KnowledgeGraph:
        """Mark the project's graph stale when source drift is detected."""
        graph = await self.ensure_graph(project_id, reason="Mark stale")
        if graph.lifecycle_status not in {"stale", "disabled"}:
            graph.lifecycle_status = "stale"
        await self._audit(
            project_id=project_id,
            event_type="knowledge_graph.marked_stale",
            title=reason,
        )
        return graph

    # ── Build helpers ─────────────────────────────────────────────────────

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

    # ── Status / recovery ─────────────────────────────────────────────────

    async def get_status(self, project_id: int) -> dict[str, Any]:
        """Return a status snapshot with builds, versions, and latest health."""
        graph = await self.ensure_graph(project_id, reason="Status check")
        versions = (
            await self.session.scalars(
                select(KnowledgeGraphVersion)
                .where(
                    KnowledgeGraphVersion.project_id == project_id,
                    KnowledgeGraphVersion.tenant_id == graph.tenant_id,
                )
                .order_by(KnowledgeGraphVersion.version_number.desc())
                .limit(MAX_VERSION_HISTORY)
            )
        ).all()
        builds = (
            await self.session.scalars(
                select(KnowledgeGraphBuild)
                .where(
                    KnowledgeGraphBuild.project_id == project_id,
                    KnowledgeGraphBuild.tenant_id == graph.tenant_id,
                )
                .order_by(KnowledgeGraphBuild.id.desc())
                .limit(MAX_VERSION_HISTORY)
            )
        ).all()
        latest_health = await self.session.scalar(
            select(KnowledgeGraphHealthCheck)
            .where(
                KnowledgeGraphHealthCheck.project_id == project_id,
                KnowledgeGraphHealthCheck.tenant_id == graph.tenant_id,
            )
            .order_by(KnowledgeGraphHealthCheck.completed_at.desc().nullslast())
        )

        active_version = await self._load_version(graph.active_version_id or 0)
        active_node_count = 0
        active_edge_count = 0
        if active_version:
            active_node_count = active_version.node_count
            active_edge_count = active_version.edge_count

        return {
            "project_id": project_id,
            "graph_id": graph.id,
            "lifecycle_status": graph.lifecycle_status,
            "enabled": graph.enabled,
            "active_version_id": graph.active_version_id,
            "active_version_number": active_version.version_number if active_version else None,
            "last_healthy_version_id": graph.last_healthy_version_id,
            "last_healthy_version_number": (
                await self._version_number(graph.last_healthy_version_id)
            ),
            "current_source_fingerprint": graph.current_source_fingerprint,
            "active_source_fingerprint": active_version.source_fingerprint if active_version else None,
            "last_successful_build_at": graph.last_successful_build_at,
            "last_health_check_at": graph.last_health_check_at,
            "active_node_count": active_node_count,
            "active_edge_count": active_edge_count,
            "health_status": latest_health.status if latest_health else "unknown",
            "has_active_version": active_version is not None,
            "versions": list(versions),
            "builds": list(builds),
        }

    async def _version_number(self, version_id: int | None) -> int | None:
        if not version_id:
            return None
        v = await self.session.get(KnowledgeGraphVersion, version_id)
        return v.version_number if v else None

    async def recover_stale_builds(self, *, older_than_seconds: int = 600) -> list[int]:
        """Find builds stuck in queued/building/validating and mark them failed."""
        cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
        builds = (
            await self.session.scalars(
                select(KnowledgeGraphBuild).where(
                    KnowledgeGraphBuild.status.in_(["queued", "building", "validating"]),
                    KnowledgeGraphBuild.heartbeat_at < cutoff,
                )
            )
        ).all()
        recovered: list[int] = []
        for build in builds:
            build.status = "failed"
            build.error_code = "stale_recovery"
            build.safe_error_message = "Build was recovered after heartbeat timeout"
            build.completed_at = datetime.now(UTC)
            build.heartbeat_at = datetime.now(UTC)
            recovered.append(build.id)
            graph = await self.session.get(KnowledgeGraph, build.graph_id)
            if graph and graph.lifecycle_status in ("building", "validating", "requested"):
                graph.lifecycle_status = "degraded"
        return recovered

    async def evaluate_stale_graphs(self) -> list[int]:
        """Find graphs whose source fingerprint drifted and mark them stale."""
        graphs = (
            await self.session.scalars(
                select(KnowledgeGraph).where(KnowledgeGraph.enabled.is_(True))
            )
        ).all()
        marked: list[int] = []
        for graph in graphs:
            fingerprint = await self.compute_source_fingerprint(graph.project_id)
            if fingerprint != (graph.current_source_fingerprint or ""):
                await self.mark_stale(
                    graph.project_id,
                    f"Source fingerprint changed from {graph.current_source_fingerprint} to {fingerprint}",
                )
                graph.current_source_fingerprint = fingerprint
                marked.append(graph.project_id)
        return marked

    async def resolve_representative_user(self, project_id: int) -> int | None:
        """Pick a user id to attribute a headless build to (project owner).

        AI enrichment only runs when a build has a ``requested_by`` user, so
        system-triggered rebuilds borrow the project owner rather than silently
        producing structural-only snapshots with no insight cards.
        """
        project = await self.session.get(Project, project_id)
        return project.owner_id if project else None

    async def get_active_snapshot_payload(
        self, project_id: int
    ) -> dict[str, Any] | None:
        """Return the active version's snapshot payload, or None."""
        graph = await self.ensure_graph(project_id, reason="Read active snapshot")
        version = await self._load_version(graph.active_version_id or 0)
        if version is None or not version.storage_reference:
            return None
        snapshot = await self.session.scalar(
            select(AIProjectGraphSnapshot).where(
                AIProjectGraphSnapshot.tenant_id == graph.tenant_id,
                AIProjectGraphSnapshot.project_id == project_id,
                AIProjectGraphSnapshot.snapshot_key == version.storage_reference,
            )
        )
        if snapshot is None:
            return None
        return _json_safe(snapshot.payload)


async def request_event_driven_rebuild(
    session: AsyncSession,
    *,
    project_id: int,
    change_set: list[dict[str, Any]],
    trigger: str,
    requested_by: int | None = None,
) -> KnowledgeGraphBuild | None:
    """Best-effort: request a rebuild for a data-change event and enqueue it.

    This is the single entry point every "project data changed" site calls
    (document processed, SaaS sync completed, project-wide reprocess). It runs
    headlessly (no request context), commits the build record, and enqueues the
    worker job. It never raises — a graph-lifecycle failure must not poison the
    data-change flow that triggered it. Returns the build, or ``None`` when the
    request could not be recorded.

    Ordering contract: call this only AFTER the underlying source rows
    (``ai_project_graph_nodes``/``ai_project_graph_edges``, staging tables) are
    committed, because the rebuild reads them; the graph is strictly a
    downstream consumer of document/relationship/family data, never a producer.
    """
    try:
        lifecycle = KnowledgeGraphLifecycleManager(session)
        if requested_by is None:
            requested_by = await lifecycle.resolve_representative_user(project_id)
        build, build_type = await lifecycle.request_incremental_rebuild(
            project_id,
            change_set=change_set,
            trigger=trigger,
            requested_by=requested_by,
        )
        await session.commit()
    except Exception:
        logger.exception(
            "Failed to record event-driven graph rebuild for project %s (%s)",
            project_id,
            trigger,
        )
        try:
            await session.rollback()
        except Exception:  # pragma: no cover - defensive
            pass
        return None

    # request_incremental_rebuild coalesces onto an already-queued build, so
    # this may re-enqueue an existing build id; the deterministic arq job id
    # in enqueue_rebuild_knowledge_graph makes that a no-op.
    try:
        from app.tasks.workflows import enqueue_rebuild_knowledge_graph

        await enqueue_rebuild_knowledge_graph(build.id)
    except Exception as exc:
        # Fail-open: the build row stays queued; the stale-build recovery cron
        # will surface it if no worker ever picks it up.
        logger.warning(
            "Failed to enqueue graph rebuild %s for project %s (%s): %s",
            build.id,
            project_id,
            trigger,
            exc,
        )
    logger.info(
        "Event-driven graph rebuild requested: project=%s build=%s type=%s trigger=%s",
        project_id,
        build.id,
        build_type,
        trigger,
    )
    return build
