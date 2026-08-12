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
    LLMDeploymentMode,
    LLMInstallation,
    LLMModelArtifact,
    LLMRoutingProfile,
    LLMRuntimeTarget,
)
from app.services.llm_model_vault import ModelVault, VaultError
from app.services.llm_ollama_adapter import OllamaAdapter

logger = logging.getLogger(__name__)


class DeploymentError(Exception):
    """A deployment step could not be completed safely."""


@dataclass(frozen=True)
class PreflightReport:
    target_reachable: bool
    disk_ok: bool
    slot_ok: bool
    capacity_ok: bool
    detail: str | None
    preflight: dict | None


def _serialize_preflight(preflight) -> dict:
    """Convert an OllamaAdapter PreflightResult to a JSON-safe dict."""
    return {
        "ollama_version": preflight.version,
        "gpu_models": [g.name for g in (preflight.gpu_infos or []) if g.name],
        "total_vram_bytes": preflight.total_vram_bytes,
        "free_vram_bytes": preflight.free_vram_bytes,
        "system_ram_bytes": preflight.system_ram_bytes,
        "free_disk_bytes": preflight.free_disk_bytes,
        "loaded_models": [m.name for m in (preflight.loaded_models or [])],
        "loaded_model_sizes": {
            m.name: m.size for m in (preflight.loaded_models or [])
        },
        "context_length": preflight.context_length,
        "max_concurrency": preflight.max_concurrency,
        "format_compatible": preflight.format_compatible,
        "warnings": preflight.warnings or [],
    }


async def preflight_install(
    session: AsyncSession,
    artifact_id: int,
    target_id: int,
    runtime_options: dict | None = None,
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
    runtime_options = runtime_options or {}
    expected_context = runtime_options.get("context_tokens")

    # App-server side: room for temp copy plus final artifact.
    # assert_disk_space adds its own 5 GiB reserve, so only pass the transient
    # requirement (temp + final) here.
    try:
        vault.assert_disk_space(vault.base_path, artifact_size * 2)
    except VaultError as exc:
        raise DeploymentError(str(exc)) from exc

    # Runtime side: Ollama reachable and capacity OK.
    adapter = OllamaAdapter(
        base_url=target.host,
        rollback_slots=settings.llm_ollama_rollback_slots,
    )
    result = await adapter.preflight(
        artifact_size=artifact_size,
        reserve_bytes=5 * 1024 ** 3,
        expected_context_tokens=expected_context,
    )

    preflight_data = _serialize_preflight(result) if result.reachable else None

    return PreflightReport(
        target_reachable=result.reachable,
        disk_ok=result.disk_ok,
        slot_ok=result.slot_ok,
        capacity_ok=result.capacity_ok,
        detail=result.detail,
        preflight=preflight_data,
    )


async def install_artifact(
    session: AsyncSession,
    artifact_id: int,
    target_id: int,
    requested_by_user_id: int,
    deployment_mode: str = LLMDeploymentMode.INSTALL_ONLY,
    runtime_options: dict | None = None,
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
        base_url=target.host,
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
        ollama_model_name=result.ollama_model_name,
        installed_at=datetime.now(UTC),
        deployment_mode=deployment_mode,
        runtime_options=runtime_options or {},
    )
    session.add(installation)
    await session.flush()
    return installation


async def create_deployment(
    session: AsyncSession,
    *,
    installation_id: int,
    target_id: int,
    requested_by_user_id: int,
    deployment_mode: str = LLMDeploymentMode.INSTALL_ONLY,
    runtime_options: dict | None = None,
    previous_deployment_id: int | None = None,
) -> LLMDeployment:
    """Record a request to activate an installation."""
    installation = await session.get(LLMInstallation, installation_id)
    if installation is None or installation.status != "installed":
        raise DeploymentError("Installation is not installed")

    deployment = LLMDeployment(
        installation_id=installation.id,
        target_id=target_id,
        requested_by_user_id=requested_by_user_id,
        previous_deployment_id=previous_deployment_id,
        status="pending",
        deployment_mode=deployment_mode,
        runtime_options=runtime_options or {},
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
    expected_version: int | None = None,
    priority: int = 1,
) -> LLMDeployment:
    """Promote an installation to the active routing profile for a capability.

    Sets the deployment status to ``stabilizing`` so the stabilization window
    can be observed before it is considered permanently active. Creates a new
    routing profile version for rollback.
    """
    from app.services.llm_framework import (
        InvalidCapabilityError,
        validate_routing_capability,
    )

    settings = get_settings()
    if not settings.llm_dynamic_routing_enabled:
        raise DeploymentError("Dynamic routing is disabled")

    deployment = await session.get(LLMDeployment, deployment_id)
    if deployment is None:
        raise DeploymentError("Deployment not found")
    required_status = "approved" if settings.llm_two_person_approval_required else "pending"
    allowed_statuses = ("approved",) if settings.llm_two_person_approval_required else ("pending", "approved")
    if deployment.status not in allowed_statuses:
        raise DeploymentError(
            f"Deployment is {deployment.status}, requires {required_status} to activate"
        )

    installation = await session.get(LLMInstallation, deployment.installation_id)
    if installation is None:
        raise DeploymentError("Installation not found")
    if installation.status != "installed":
        raise DeploymentError("Installation is not installed")

    try:
        normalized = await validate_routing_capability(capability)
    except InvalidCapabilityError as exc:
        raise DeploymentError(str(exc)) from exc

    if target_id != installation.target_id:
        raise DeploymentError("Activation target must match installation target")

    # Deactivate the current active profile and create a new version row.
    active_profile = await session.scalar(
        select(LLMRoutingProfile).where(
            LLMRoutingProfile.capability == normalized,
            LLMRoutingProfile.is_active.is_(True),
        )
    )
    if expected_version is not None:
        if active_profile is None or active_profile.version != expected_version:
            raise DeploymentError(
                f"Routing version mismatch: expected {expected_version}, "
                f"found {active_profile.version if active_profile else 'none'}"
            )

    next_version = 1
    if active_profile is not None:
        next_version = active_profile.version + 1
        active_profile.is_active = False

    new_profile = LLMRoutingProfile(
        capability=normalized,
        target_id=target_id,
        installation_id=installation.id,
        deployment_id=deployment.id,
        is_active=True,
        priority=priority,
        version=next_version,
        previous_routing_profile_id=active_profile.id if active_profile else None,
        config={"installation_id": installation.id, "deployment_id": deployment.id},
    )
    session.add(new_profile)
    await session.flush()

    if active_profile is not None:
        active_profile.superseded_by_id = new_profile.id

    installation.activated_at = datetime.now(UTC)
    installation.status = "active"
    deployment.status = "stabilizing"
    await session.flush()
    return deployment


async def rollback_deployment(
    session: AsyncSession,
    deployment_id: int,
) -> LLMDeployment:
    """Revert a deployment to its previous routing profile if available."""
    deployment = await session.get(LLMDeployment, deployment_id)
    if deployment is None:
        raise DeploymentError("Deployment not found")

    installation = await session.get(LLMInstallation, deployment.installation_id)
    if installation is None:
        raise DeploymentError("Installation not found")

    # Find the routing profile created by this deployment and deactivate it.
    profile = await session.scalar(
        select(LLMRoutingProfile).where(
            LLMRoutingProfile.deployment_id == deployment.id,
            LLMRoutingProfile.is_active.is_(True),
        )
    )

    previous_profile = None
    if profile is not None:
        previous_profile = profile.previous_profile
        profile.is_active = False
        if previous_profile is not None:
            previous_profile.is_active = True
            previous_profile.superseded_by_id = None

    # If no routing profile was created (e.g. install-only), try the deployment
    # chain for a previous installation.
    if previous_profile is None and deployment.previous_deployment_id:
        previous_deployment = await session.get(LLMDeployment, deployment.previous_deployment_id)
        if previous_deployment and previous_deployment.installation_id:
            previous_installation = await session.get(
                LLMInstallation, previous_deployment.installation_id
            )
            if previous_installation:
                previous_profile = await session.scalar(
                    select(LLMRoutingProfile).where(
                        LLMRoutingProfile.installation_id == previous_installation.id,
                    )
                    .order_by(LLMRoutingProfile.version.desc())
                    .limit(1)
                )
                if previous_profile is not None:
                    previous_profile.is_active = True
                    previous_profile.superseded_by_id = None

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

    target = await session.get(LLMRuntimeTarget, deployment.target_id)
    if target is None:
        return await rollback_deployment(session, deployment_id)

    adapter = OllamaAdapter(base_url=target.host)
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
