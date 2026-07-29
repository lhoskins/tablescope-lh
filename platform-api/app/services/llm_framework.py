"""LLM Framework read-only inventory and lightweight lifecycle helpers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_framework import (
    LLMInstallation,
    LLMModelArtifact,
    LLMRoutingProfile,
    LLMRuntimeTarget,
)

CAPABILITIES = [
    "generate",
    "chat",
    "embed",
    "summarize",
    "classify",
    "code",
]


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
