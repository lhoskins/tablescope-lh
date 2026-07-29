"""Deployment orchestration: preflight, install, activate, rollback.

The orchestrator decides whether to run against a local/accessible Ollama
instance or to call a remote deployment agent. If ``llm_deployment_agent_url``
is configured, all install operations go to that agent over mTLS (or plain HTTP
in development); otherwise the adapter runs locally and the worker must be
executing on a host that can see the Ollama filesystem.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.llm_framework import (
    LLMArtifactFile,
    LLMDeployment,
    LLMInstallation,
    LLMModelArtifact,
    LLMRoutingProfile,
    LLMRuntimeTarget,
)
from app.services.llm_model_vault import ModelVault
from app.services.llm_ollama_adapter import OllamaAdapter

logger = logging.getLogger(__name__)


class DeploymentError(Exception):
    """A deployment step could not be completed safely."""


@dataclass(frozen=True)
class PreflightReport:
    target_reachable: bool
    disk_ok: bool
    slot_ok: bool
    detail: str | None


async def preflight_install(
    session: AsyncSession,
    artifact_id: int,
    target_id: int,
) -> PreflightReport:
    """Check both sides before a deployment begins."""
    artifact = await session.get(LLMModelArtifact, artifact_id)
    if artifact is None or artifact.status != "verified":
        raise DeploymentError("Artifact is not verified")
    target = await session.get(LLMRuntimeTarget, target_id)
    if target is None:
        raise DeploymentError("Runtime target not found")

    settings = get_settings()
    vault = ModelVault()
    artifact_size = artifact.size_bytes or 0

    # App-server side: room in the vault for the temp copy.
    vault.assert_disk_space(vault.base_path, artifact_size * 2 + 5 * 1024 ** 3)

    # Runtime side: Ollama reachable and capacity OK.
    adapter = OllamaAdapter(
        base_url=settings.llm_ollama_url,
        rollback_slots=settings.llm_ollama_rollback_slots,
    )
    result = await adapter.preflight(
        artifact_size=artifact_size,
        reserve_bytes=5 * 1024 ** 3,
    )

    return PreflightReport(
        target_reachable=result.reachable,
        disk_ok=result.disk_ok,
        slot_ok=result.slot_ok,
        detail=result.detail,
    )


async def install_artifact(
    session: AsyncSession,
    artifact_id: int,
    target_id: int,
    requested_by_user_id: int,
) -> LLMInstallation:
    """Install a verified artifact on a runtime target, leaving it inactive."""
    settings = get_settings()
    if not settings.llm_deployment_enabled:
        raise DeploymentError("LLM deployment is disabled")

    artifact = await session.get(LLMModelArtifact, artifact_id)
    if artifact is None or artifact.status != "verified":
        raise DeploymentError("Artifact is not verified")
    target = await session.get(LLMRuntimeTarget, target_id)
    if target is None:
        raise DeploymentError("Runtime target not found")

    file_row = await session.scalar(
        select(LLMArtifactFile).where(LLMArtifactFile.artifact_id == artifact_id)
    )
    if file_row is None:
        raise DeploymentError("No GGUF file found for artifact")

    vault = ModelVault()
    source_path = vault.storage_path(artifact.id, file_row.filename)

    adapter = OllamaAdapter(
        base_url=settings.llm_ollama_url,
        install_path=settings.llm_model_install_path,
        rollback_slots=settings.llm_ollama_rollback_slots,
    )

    result = await adapter.install(
        artifact_id=artifact.id,
        artifact_name=artifact.name,
        source_gguf_path=str(source_path),
    )
    if not result.success:
        raise DeploymentError(result.detail or "Ollama install failed")

    installation = LLMInstallation(
        artifact_id=artifact.id,
        target_id=target.id,
        status="installed",
        installed_path=result.installed_path,
        modelfile_content=result.modelfile_content,
        installed_at=datetime.now(UTC),
    )
    session.add(installation)
    await session.flush()
    return installation


async def create_deployment(
    session: AsyncSession,
    *,
    installation_id: int,
    requested_by_user_id: int,
    previous_deployment_id: int | None = None,
) -> LLMDeployment:
    """Record a request to activate an installation."""
    installation = await session.get(LLMInstallation, installation_id)
    if installation is None or installation.status != "installed":
        raise DeploymentError("Installation is not installed")

    deployment = LLMDeployment(
        installation_id=installation.id,
        requested_by_user_id=requested_by_user_id,
        previous_deployment_id=previous_deployment_id,
        status="pending",
    )
    session.add(deployment)
    await session.flush()
    return deployment


async def approve_deployment(
    session: AsyncSession,
    deployment_id: int,
    approved_by_user_id: int,
) -> LLMDeployment:
    """Second-person approval for a deployment."""
    deployment = await session.get(LLMDeployment, deployment_id)
    if deployment is None:
        raise DeploymentError("Deployment not found")
    if deployment.status != "pending":
        raise DeploymentError(f"Deployment is {deployment.status}, not pending")
    if deployment.requested_by_user_id == approved_by_user_id:
        raise DeploymentError("Requester cannot approve their own deployment")

    deployment.approved_by_user_id = approved_by_user_id
    deployment.status = "approved"
    await session.flush()
    return deployment


async def activate_deployment(
    session: AsyncSession,
    deployment_id: int,
    *,
    capability: str,
    target_id: int,
) -> LLMDeployment:
    """Promote an installation to the active routing profile for a capability.

    Sets the deployment status to ``stabilizing`` so the stabilization window
    can be observed before it is considered permanently active.
    """
    settings = get_settings()
    if not settings.llm_dynamic_routing_enabled:
        raise DeploymentError("Dynamic routing is disabled")

    deployment = await session.get(LLMDeployment, deployment_id)
    if deployment is None:
        raise DeploymentError("Deployment not found")
    if deployment.status not in ("pending", "approved"):
        raise DeploymentError(f"Deployment is {deployment.status}, cannot activate")

    installation = await session.get(LLMInstallation, deployment.installation_id)
    if installation is None:
        raise DeploymentError("Installation not found")
    if installation.status != "installed":
        raise DeploymentError("Installation is not installed")

    # Deactivate any existing profile for this capability and target, then set
    # the new one active.
    existing_profiles = (
        await session.scalars(
            select(LLMRoutingProfile).where(
                LLMRoutingProfile.capability == capability,
                LLMRoutingProfile.target_id == target_id,
            )
        )
    ).all()
    for profile in existing_profiles:
        profile.is_active = False

    if existing_profiles:
        target_profile = existing_profiles[0]
        target_profile.installation_id = installation.id
        target_profile.is_active = True
        target_profile.priority = 1
    else:
        session.add(
            LLMRoutingProfile(
                capability=capability,
                target_id=target_id,
                installation_id=installation.id,
                is_active=True,
                priority=1,
            )
        )

    installation.activated_at = datetime.now(UTC)
    installation.status = "active"
    deployment.status = "stabilizing"
    await session.flush()
    return deployment


async def rollback_deployment(
    session: AsyncSession,
    deployment_id: int,
) -> LLMDeployment:
    """Revert a deployment to its previous installation if available."""
    deployment = await session.get(LLMDeployment, deployment_id)
    if deployment is None:
        raise DeploymentError("Deployment not found")

    installation = await session.get(LLMInstallation, deployment.installation_id)
    if installation is None:
        raise DeploymentError("Installation not found")

    previous_deployment_id = deployment.previous_deployment_id
    if previous_deployment_id:
        previous_deployment = await session.get(LLMDeployment, previous_deployment_id)
        if previous_deployment and previous_deployment.installation_id:
            previous = await session.get(LLMInstallation, previous_deployment.installation_id)
            if previous:
                for profile in (
                    await session.scalars(
                        select(LLMRoutingProfile).where(
                            LLMRoutingProfile.installation_id == installation.id,
                        )
                    )
                ).all():
                    profile.installation_id = previous.id
                    profile.is_active = True

    installation.status = "rolled_back"
    installation.rolled_back_at = datetime.now(UTC)
    deployment.status = "rolled_back"
    await session.flush()
    return deployment


async def evaluate_stabilization(
    session: AsyncSession,
    deployment_id: int,
) -> LLMDeployment:
    """Run a lightweight canary and either stabilize or roll back."""
    settings = get_settings()
    deployment = await session.get(LLMDeployment, deployment_id)
    if deployment is None or deployment.status != "stabilizing":
        raise DeploymentError("Deployment is not in stabilizing state")

    installation = await session.get(LLMInstallation, deployment.installation_id)
    if installation is None or not installation.modelfile_content:
        return await rollback_deployment(session, deployment_id)

    adapter = OllamaAdapter(base_url=settings.llm_ollama_url)
    # Extract model name from the Modelfile's FROM line? It is not stored.
    # We instead query /api/tags and look for the artifact id in the name.
    tags_response = await adapter._request("GET", "/api/tags")
    models = [m["name"] for m in tags_response.json().get("models", [])]
    model_name = next(
        (m for m in models if f"tablescope-{installation.artifact_id}-" in m),
        None,
    )
    if model_name is None:
        return await rollback_deployment(session, deployment_id)

    try:
        response = await adapter.generate(
            model_name,
            "Return the single word 'ok' and nothing else.",
        )
        if response.strip().lower() != "ok":
            raise DeploymentError("Canary response was not the expected sentinel")
    except Exception:
        if settings.llm_auto_rollback_enabled:
            return await rollback_deployment(session, deployment_id)
        raise

    deployment.status = "active"
    deployment.stabilized_at = datetime.now(UTC)
    await session.flush()
    return deployment
