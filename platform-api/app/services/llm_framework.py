"""LLM Framework read-only inventory and lightweight lifecycle helpers."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.llm_framework import (
    ROUTING_CAPABILITIES,
    LLMInstallation,
    LLMModelArtifact,
    LLMRoutingProfile,
    LLMRuntimeTarget,
)
from app.services.llm_catalog_client import CatalogModel, HuggingFaceCatalogClient

logger = logging.getLogger(__name__)

CAPABILITIES = ROUTING_CAPABILITIES


class InvalidCapabilityError(ValueError):
    """Raised when a capability is not routable or is explicitly excluded."""


async def validate_routing_capability(capability: str) -> str:
    """Return a normalized capability label if it is routable.

    ``embedding`` is rejected even if a caller passes it, because swapping an
    embedding model silently invalidates existing Qdrant vectors. See §1.2.
    """
    normalized = capability.strip().lower()
    if normalized == "embed" or normalized == "embedding":
        raise InvalidCapabilityError(
            "Embedding models cannot be routed through the LLM framework; "
            "they require a separate re-index migration."
        )
    if normalized not in ROUTING_CAPABILITIES:
        raise InvalidCapabilityError(
            f"'{capability}' is not a routable capability. "
            f"Routable capabilities are: {', '.join(ROUTING_CAPABILITIES)}"
        )
    return normalized


async def get_inventory(session: AsyncSession) -> dict:
    """Return the full LLM framework inventory from the database."""
    targets = (await session.scalars(select(LLMRuntimeTarget).order_by(LLMRuntimeTarget.name))).all()
    artifacts = (
        await session.scalars(
            select(LLMModelArtifact).order_by(LLMModelArtifact.name, LLMModelArtifact.id)
        )
    ).all()
    installations = (
        await session.scalars(
            select(LLMInstallation)
            .order_by(LLMInstallation.created_at.desc())
        )
    ).all()
    routing_profiles = (
        await session.scalars(
            select(LLMRoutingProfile)
            .order_by(LLMRoutingProfile.capability, LLMRoutingProfile.priority.desc())
        )
    ).all()

    return {
        "targets": targets,
        "artifacts": artifacts,
        "installations": installations,
        "routing_profiles": routing_profiles,
    }


async def get_artifact(session: AsyncSession, artifact_id: int) -> LLMModelArtifact | None:
    stmt = (
        select(LLMModelArtifact)
        .where(LLMModelArtifact.id == artifact_id)
        .options(selectinload(LLMModelArtifact.files))
        .options(selectinload(LLMModelArtifact.license_approval))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def release_quarantined_artifact(
    session: AsyncSession,
    artifact_id: int,
) -> LLMModelArtifact | None:
    """Move a quarantined artifact back to staged so verification can be retried."""
    artifact = await session.get(LLMModelArtifact, artifact_id)
    if artifact is None:
        return None
    if artifact.status != "quarantined":
        return artifact
    artifact.status = "staged"
    artifact.quarantine_reason = None
    await session.flush()
    return artifact


def _repo_id_from_url(repo_url: str) -> str:
    parsed = urlparse(repo_url)
    path = parsed.path.strip("/")
    if parsed.netloc not in ("huggingface.co", "www.huggingface.co"):
        raise ValueError("Repository URL must be on huggingface.co")
    if "/" not in path:
        raise ValueError("Repository URL must contain the publisher and name")
    return path


async def search_catalog(query: str, *, limit: int = 20) -> list[CatalogModel]:
    """Search the Hugging Face catalog for models matching the query."""
    client = HuggingFaceCatalogClient()
    return await client.search(query, limit=limit)


async def get_catalog_detail(repo_url: str) -> CatalogModel:
    """Fetch detailed catalog metadata for a single repository."""
    client = HuggingFaceCatalogClient()
    repo_id = _repo_id_from_url(repo_url)
    return await client.get_model_info(repo_id)


async def create_artifact_and_stage(
    session: AsyncSession,
    *,
    repo_url: str,
    quantization: str | None,
    name: str | None,
    requested_by_user_id: int,
) -> tuple[LLMModelArtifact, str]:
    """Create an artifact row and enqueue the worker staging task.

    The worker will validate the repository, license, and GGUF contents.
    """
    repo_id = _repo_id_from_url(repo_url)
    publisher, repo_name = repo_id.split("/", 1)

    artifact_name = name or f"{repo_name.replace('-', ' ').replace('_', ' ')} GGUF"
    artifact = LLMModelArtifact(
        name=artifact_name,
        publisher=publisher,
        repo_url=repo_url,
        quantization=quantization,
        format="gguf",
        status="pending",
        requested_by_user_id=requested_by_user_id,
    )
    session.add(artifact)
    await session.flush()

    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    pool = await create_pool(redis_settings)
    try:
        job = await pool.enqueue_job(
            "stage_llm_artifact",
            artifact_id=artifact.id,
            requested_by_user_id=requested_by_user_id,
        )
        job_id = job.job_id if job else ""
    finally:
        await pool.close()

    artifact.staged_job_id = job_id
    await session.flush()
    return artifact, job_id


async def enqueue_stage_llm_artifact(
    artifact_id: int,
    requested_by_user_id: int,
) -> str:
    """Enqueue an existing artifact for re-staging (quarantine release path)."""
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    pool = await create_pool(redis_settings)
    try:
        job = await pool.enqueue_job(
            "stage_llm_artifact",
            artifact_id=artifact_id,
            requested_by_user_id=requested_by_user_id,
        )
        return job.job_id if job else ""
    finally:
        await pool.close()
