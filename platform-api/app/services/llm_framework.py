"""LLM Framework read-only inventory and lightweight lifecycle helpers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from urllib.parse import urlparse

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.llm_framework import (
    ROUTING_CAPABILITIES,
    LLMAuditEvent,
    LLMDeployment,
    LLMInstallation,
    LLMModelArtifact,
    LLMRoutingProfile,
    LLMRuntimeTarget,
)
from app.services.llm_catalog_client import CatalogModel, HuggingFaceCatalogClient
from app.services.llm_ollama_adapter import OllamaAdapter

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


async def get_active_routing_model(session: AsyncSession, capability: str) -> str | None:
    """Return the active Ollama model name for a routable capability, if any."""
    try:
        normalized = await validate_routing_capability(capability)
    except InvalidCapabilityError:
        return None
    stmt = (
        select(LLMRoutingProfile)
        .where(
            LLMRoutingProfile.capability == normalized,
            LLMRoutingProfile.is_active.is_(True),
        )
        .options(selectinload(LLMRoutingProfile.installation))
        .order_by(LLMRoutingProfile.priority.desc())
        .limit(1)
    )
    try:
        profile = (await session.execute(stmt)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        logger.warning("Failed to resolve active LLM routing profile: %s", exc)
        return None
    if profile is None or profile.installation is None:
        return None
    return profile.installation.ollama_model_name


async def resolve_active_model_for_capability(capability: str) -> str | None:
    """Resolve the active model for a capability using a short-lived session.

    Returns ``None`` when dynamic routing is disabled or no active profile exists,
    letting the AI server fall back to its static defaults.
    """
    settings = get_settings()
    if not settings.llm_dynamic_routing_enabled:
        return None
    from app.database import SessionLocal

    async with SessionLocal() as session:
        return await get_active_routing_model(session, capability)


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


class DuplicateRuntimeTargetError(ValueError):
    """Raised when a target with the same name already exists."""


async def register_runtime_target(
    session: AsyncSession,
    *,
    name: str,
    host: str,
    runtime_type: str = "ollama",
    version: str | None = None,
    max_loaded_models: int | None = None,
    keep_alive_minutes: int | None = None,
    labels: dict | None = None,
) -> LLMRuntimeTarget:
    """Register a runtime target. Probes reachability but does not require it."""
    existing = await session.scalar(
        select(LLMRuntimeTarget).where(LLMRuntimeTarget.name == name)
    )
    if existing is not None:
        raise DuplicateRuntimeTargetError(f"A runtime target named '{name}' already exists")

    is_reachable = False
    last_seen_at = None
    if runtime_type == "ollama":
        try:
            result = await OllamaAdapter(base_url=host).preflight(
                artifact_size=0, reserve_bytes=0
            )
            is_reachable = result.reachable
            if is_reachable:
                last_seen_at = datetime.now(UTC)
        except Exception:
            logger.warning("Reachability probe failed for new target %s (%s)", name, host)

    target = LLMRuntimeTarget(
        name=name,
        runtime_type=runtime_type,
        host=host,
        version=version,
        status="active",
        is_reachable=is_reachable,
        last_seen_at=last_seen_at,
        max_loaded_models=max_loaded_models,
        keep_alive_minutes=keep_alive_minutes,
        labels=labels or {},
    )
    session.add(target)
    await session.flush()
    return target


async def ensure_primary_runtime_target_registered(session: AsyncSession) -> None:
    """Idempotently register the configured primary Ollama target on startup."""
    settings = get_settings()
    existing = await session.scalar(
        select(LLMRuntimeTarget).where(LLMRuntimeTarget.host == settings.llm_ollama_url)
    )
    if existing is not None:
        return
    try:
        await register_runtime_target(
            session, name="primary-ollama", host=settings.llm_ollama_url
        )
        await session.commit()
    except DuplicateRuntimeTargetError:
        await session.rollback()


async def list_deployments(session: AsyncSession, *, limit: int = 50) -> list[dict]:
    """Return deployments joined with artifact and target names, newest first."""
    rows = (
        await session.execute(
            select(LLMDeployment, LLMInstallation, LLMModelArtifact, LLMRuntimeTarget)
            .join(LLMInstallation, LLMDeployment.installation_id == LLMInstallation.id)
            .join(LLMModelArtifact, LLMInstallation.artifact_id == LLMModelArtifact.id)
            .join(LLMRuntimeTarget, LLMInstallation.target_id == LLMRuntimeTarget.id)
            .order_by(LLMDeployment.created_at.desc())
            .limit(min(limit, 200))
        )
    ).all()
    return [
        {
            "id": d.id,
            "installation_id": d.installation_id,
            "artifact_id": a.id,
            "artifact_name": a.name,
            "target_id": t.id,
            "target_name": t.name,
            "requested_by_user_id": d.requested_by_user_id,
            "approved_by_user_id": d.approved_by_user_id,
            "status": d.status,
            "previous_deployment_id": d.previous_deployment_id,
            "stabilized_at": d.stabilized_at,
            "created_at": d.created_at,
            "updated_at": d.updated_at,
        }
        for d, i, a, t in rows
    ]


async def record_llm_audit_event(
    session: AsyncSession,
    *,
    actor_user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None,
    details: dict | None = None,
) -> None:
    """Write a platform-scoped audit event for an LLM framework action."""
    session.add(
        LLMAuditEvent(
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )


async def upsert_routing_profile(
    session: AsyncSession,
    *,
    capability: str,
    target_id: int,
    installation_id: int,
    priority: int = 1,
    is_active: bool = True,
) -> LLMRoutingProfile:
    """Create or update a routing profile and ensure at most one active profile per capability."""
    normalized = await validate_routing_capability(capability)
    target = await session.get(LLMRuntimeTarget, target_id)
    if target is None:
        raise ValueError("Runtime target not found")
    installation = await session.get(LLMInstallation, installation_id)
    if installation is None or installation.status != "installed":
        raise ValueError("Installation is not installed")

    profile = await session.scalar(
        select(LLMRoutingProfile).where(
            LLMRoutingProfile.capability == normalized,
            LLMRoutingProfile.target_id == target_id,
            LLMRoutingProfile.installation_id == installation_id,
        )
    )
    if profile is None:
        profile = LLMRoutingProfile(
            capability=normalized,
            target_id=target_id,
            installation_id=installation_id,
        )
        session.add(profile)

    if is_active:
        for existing in (
            await session.scalars(
                select(LLMRoutingProfile).where(
                    LLMRoutingProfile.capability == normalized,
                    LLMRoutingProfile.is_active.is_(True),
                )
            )
        ).all():
            existing.is_active = False

    profile.is_active = is_active
    profile.priority = priority
    profile.config = {"installation_id": installation_id}
    await session.flush()
    return profile


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
    return await client.get_model_detail(repo_id)


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


async def enqueue_deploy_llm_artifact(
    artifact_id: int,
    target_id: int,
    requested_by_user_id: int,
) -> str:
    """Enqueue a verified artifact for installation on a runtime target."""
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    pool = await create_pool(redis_settings)
    try:
        job = await pool.enqueue_job(
            "deploy_llm_artifact",
            artifact_id=artifact_id,
            target_id=target_id,
            requested_by_user_id=requested_by_user_id,
        )
        return job.job_id if job else ""
    finally:
        await pool.close()
