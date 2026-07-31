"""Phase 5: embedding model re-index migration orchestration.

The platform-api owns the migration record, authorization, and queueing; the
actual dual-collection re-index and recall comparison happen in the AI server,
which has direct access to Qdrant and Ollama.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.llm_framework import LLMEmbeddingMigration, LLMModelArtifact
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)


class EmbeddingMigrationError(Exception):
    """A migration step could not be completed safely."""


def _sign_payload(payload: dict[str, Any], secret: str) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


async def _call_ai_reindex(
    tenant_id: int,
    source_collection: str,
    target_collection: str,
    embedding_model: str,
    embedding_dim: int,
) -> dict[str, Any]:
    settings = get_settings()
    url = settings.tablescope_ai_api_url.rstrip("/") + "/internal/vector-store/reindex"
    payload = {
        "tenant_id": tenant_id,
        "source_collection": source_collection,
        "target_collection": target_collection,
        "embedding_model": embedding_model,
        "embedding_dim": embedding_dim,
        "timestamp": time.time(),
    }
    payload["signature"] = _sign_payload(payload, settings.tablescope_ai_signing_secret)
    body = json.dumps(payload, default=str, ensure_ascii=False)

    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        resp = await client.post(
            url,
            content=body.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


async def start_embedding_migration(
    session: AsyncSession,
    *,
    artifact_id: int,
    tenant_id: int,
    embedding_model: str,
    embedding_dim: int,
    requested_by_user_id: int,
) -> LLMEmbeddingMigration:
    """Create a migration row for a tenant and enqueue the worker."""
    artifact = await session.get(LLMModelArtifact, artifact_id)
    if artifact is None:
        raise EmbeddingMigrationError("Artifact not found")
    if artifact.format != "gguf":
        raise EmbeddingMigrationError("Only GGUF artifacts can be used for embedding migration")

    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise EmbeddingMigrationError("Tenant not found")

    existing = await session.scalar(
        select(LLMEmbeddingMigration).where(
            LLMEmbeddingMigration.artifact_id == artifact_id,
            LLMEmbeddingMigration.tenant_id == tenant_id,
            LLMEmbeddingMigration.status.notin_(["completed", "failed", "rolled_back"]),
        )
    )
    if existing:
        raise EmbeddingMigrationError("An active migration already exists for this artifact and tenant")

    source = f"tablescope_tenant_{tenant_id}"
    target = f"{source}_migration_{int(time.time())}"

    migration = LLMEmbeddingMigration(
        tenant_id=tenant_id,
        artifact_id=artifact_id,
        source_collection=source,
        target_collection=target,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        status="pending",
    )
    session.add(migration)
    await session.flush()
    return migration


async def run_embedding_migration(session: AsyncSession, migration_id: int) -> dict[str, Any]:
    """Run the migration by calling the AI server and update the record."""
    migration = await session.get(LLMEmbeddingMigration, migration_id)
    if migration is None:
        raise EmbeddingMigrationError("Migration not found")

    migration.status = "creating_target"
    await session.flush()

    try:
        result = await _call_ai_reindex(
            tenant_id=migration.tenant_id,
            source_collection=migration.source_collection,
            target_collection=migration.target_collection,
            embedding_model=migration.embedding_model,
            embedding_dim=migration.embedding_dim,
        )
    except Exception as exc:
        logger.exception("AI server reindex failed for migration %s", migration_id)
        migration.status = "failed"
        migration.detail = str(exc)[:1024]
        await session.flush()
        return {"migration_id": migration_id, "status": "failed", "reason": str(exc)}

    migration.status = "comparing"
    await session.flush()

    migration.points_total = result.get("points_total")
    migration.points_indexed = result.get("points_indexed")
    migration.recall_score = result.get("recall_score")

    threshold = get_settings().llm_embedding_recall_threshold
    if migration.recall_score is not None and migration.recall_score < threshold:
        migration.status = "failed"
        migration.detail = (
            f"Recall score {migration.recall_score:.3f} is below threshold {threshold}; "
            "manual review required before cut-over."
        )
    else:
        migration.status = "completed"
        migration.detail = None

    await session.flush()
    return {
        "migration_id": migration_id,
        "status": migration.status,
        "points_total": migration.points_total,
        "points_indexed": migration.points_indexed,
        "recall_score": migration.recall_score,
    }


async def rollback_embedding_migration(session: AsyncSession, migration_id: int) -> LLMEmbeddingMigration:
    """Mark a migration as rolled back."""
    migration = await session.get(LLMEmbeddingMigration, migration_id)
    if migration is None:
        raise EmbeddingMigrationError("Migration not found")
    migration.status = "rolled_back"
    await session.flush()
    return migration
