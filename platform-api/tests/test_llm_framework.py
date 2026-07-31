"""Tests for the LLM Framework service layer."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.llm_framework import (
    ROUTING_CAPABILITIES,
    LLMAuditEvent,
    LLMDeployment,
    LLMInstallation,
    LLMModelArtifact,
    LLMRuntimeTarget,
)
from app.services.llm_deployment import DeploymentError, activate_deployment
from app.services.llm_framework import (
    CAPABILITIES,
    DuplicateRuntimeTargetError,
    InvalidCapabilityError,
    ensure_primary_runtime_target_registered,
    list_deployments,
    record_llm_audit_event,
    register_runtime_target,
    validate_routing_capability,
)

pytestmark = pytest.mark.anyio


def test_routing_capabilities_excludes_embed() -> None:
    assert "embed" not in ROUTING_CAPABILITIES
    assert "embedding" not in ROUTING_CAPABILITIES


def test_service_capabilities_match_model() -> None:
    assert sorted(CAPABILITIES) == sorted(ROUTING_CAPABILITIES)


async def test_validate_routing_capability_accepts_routable() -> None:
    assert await validate_routing_capability("sql_generation") == "sql_generation"


async def test_validate_routing_capability_rejects_embed() -> None:
    with pytest.raises(InvalidCapabilityError) as exc:
        await validate_routing_capability("embed")
    assert "re-index" in str(exc.value).lower() or "embedding" in str(exc.value).lower()


async def test_validate_routing_capability_rejects_unknown() -> None:
    with pytest.raises(InvalidCapabilityError) as exc:
        await validate_routing_capability("code")
    assert "not a routable capability" in str(exc.value)


def _fake_ollama_adapter(monkeypatch, reachable: bool = True) -> None:
    class FakeAdapter:
        def __init__(self, base_url: str | None = None, install_path: str | None = None) -> None:
            pass

        async def preflight(self, artifact_size: int, reserve_bytes: int = 0):
            return SimpleNamespace(reachable=reachable, version="0.0", disk_ok=True, slot_ok=True, detail=None)

    monkeypatch.setattr("app.services.llm_framework.OllamaAdapter", FakeAdapter)


async def test_register_runtime_target_creates_target(db_session, monkeypatch):
    _fake_ollama_adapter(monkeypatch, reachable=True)
    target = await register_runtime_target(
        db_session, name="primary", host="http://ollama:11434"
    )
    assert target.name == "primary"
    assert target.runtime_type == "ollama"
    assert target.is_reachable is True
    assert target.status == "active"


async def test_register_runtime_target_rejects_duplicate(db_session, monkeypatch):
    _fake_ollama_adapter(monkeypatch, reachable=True)
    await register_runtime_target(db_session, name="primary", host="http://ollama:11434")
    with pytest.raises(DuplicateRuntimeTargetError):
        await register_runtime_target(db_session, name="primary", host="http://ollama:11434")


async def test_register_runtime_target_skips_probe_for_non_ollama(db_session, monkeypatch):
    target = await register_runtime_target(
        db_session, name="local", host="/tmp/model.sock", runtime_type="local"
    )
    assert target.is_reachable is False
    assert target.last_seen_at is None


async def test_ensure_primary_runtime_target_is_idempotent(db_session, monkeypatch):
    _fake_ollama_adapter(monkeypatch, reachable=True)
    await ensure_primary_runtime_target_registered(db_session)
    first = (await db_session.scalars(select(LLMRuntimeTarget))).all()
    await ensure_primary_runtime_target_registered(db_session)
    second = (await db_session.scalars(select(LLMRuntimeTarget))).all()
    assert len(first) == 1
    assert first == second


async def test_record_llm_audit_event(db_session):
    await record_llm_audit_event(
        db_session,
        actor_user_id=1,
        action="register_target",
        entity_type="runtime_target",
        entity_id=42,
        details={"host": "http://ollama:11434"},
    )
    await db_session.commit()
    events = (await db_session.scalars(select(LLMAuditEvent).order_by(LLMAuditEvent.id))).all()
    assert len(events) == 1
    assert events[0].action == "register_target"
    assert events[0].entity_id == 42


async def _seed_deployment(db_session):
    target = LLMRuntimeTarget(name="target", runtime_type="ollama", host="http://x", status="active", labels={})
    artifact = LLMModelArtifact(name="artifact", format="gguf", status="verified", manifest={})
    db_session.add_all([target, artifact])
    await db_session.flush()
    installation = LLMInstallation(artifact_id=artifact.id, target_id=target.id, status="installed")
    db_session.add(installation)
    await db_session.flush()
    deployment = LLMDeployment(
        installation_id=installation.id,
        requested_by_user_id=1,
        status="active",
    )
    db_session.add(deployment)
    await db_session.flush()
    return target, artifact, installation, deployment


async def test_list_deployments_joins_artifact_and_target_names(db_session):
    target, artifact, installation, deployment = await _seed_deployment(db_session)
    summaries = await list_deployments(db_session)
    assert len(summaries) == 1
    assert summaries[0]["id"] == deployment.id
    assert summaries[0]["artifact_name"] == artifact.name
    assert summaries[0]["target_name"] == target.name


async def test_activate_deployment_requires_approval_when_two_person_enabled(db_session, monkeypatch):
    target, artifact, installation, deployment = await _seed_deployment(db_session)
    deployment.status = "pending"
    monkeypatch.setattr(
        "app.services.llm_deployment.get_settings",
        lambda: SimpleNamespace(
            llm_dynamic_routing_enabled=True,
            llm_two_person_approval_required=True,
        ),
    )
    with pytest.raises(DeploymentError) as exc:
        await activate_deployment(db_session, deployment.id, capability="sql_generation", target_id=target.id)
    assert "approved" in str(exc.value).lower()


async def test_activate_deployment_succeeds_when_approved_and_two_person_enabled(db_session, monkeypatch):
    target, artifact, installation, deployment = await _seed_deployment(db_session)
    deployment.status = "approved"
    deployment.approved_by_user_id = 2
    monkeypatch.setattr(
        "app.services.llm_deployment.get_settings",
        lambda: SimpleNamespace(
            llm_dynamic_routing_enabled=True,
            llm_two_person_approval_required=True,
        ),
    )
    activated = await activate_deployment(db_session, deployment.id, capability="sql_generation", target_id=target.id)
    assert activated.status == "stabilizing"
    assert installation.status == "active"


async def test_activate_deployment_succeeds_when_pending_and_two_person_disabled(db_session, monkeypatch):
    target, artifact, installation, deployment = await _seed_deployment(db_session)
    deployment.status = "pending"
    monkeypatch.setattr(
        "app.services.llm_deployment.get_settings",
        lambda: SimpleNamespace(
            llm_dynamic_routing_enabled=True,
            llm_two_person_approval_required=False,
        ),
    )
    activated = await activate_deployment(db_session, deployment.id, capability="sql_generation", target_id=target.id)
    assert activated.status == "stabilizing"
