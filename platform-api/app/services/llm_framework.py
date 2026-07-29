"""LLM Framework read-only inventory and lightweight lifecycle helpers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_framework import (
    ROUTING_CAPABILITIES,
    LLMInstallation,
    LLMModelArtifact,
    LLMRoutingProfile,
    LLMRuntimeTarget,
)

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
    return await session.get(LLMModelArtifact, artifact_id)


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
