
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_governance_audit import AIGovernanceAuditEvent
from app.models.tenant_ai_governance import (
    TenantAIGovernancePolicy,
    TenantAIMethodPolicy,
)

from .registry import _INSIGHT_TYPE_METHOD as _INSIGHT_TYPE_METHOD
from .registry import _METHOD_BY_KEY, METHOD_REGISTRY, infer_governance_key, logger
from .registry import AnalyticalMethodDefinition as AnalyticalMethodDefinition
from .registry import get_method_definition as get_method_definition
from .registry import get_method_label as get_method_label
from .registry import list_method_definitions as list_method_definitions

"""Tenant AI governance policy service.

Provides an authoritative registry of governable analytical methods, per-tenant
policy evaluation, administrative updates, and an append-only audit log.

The registry keys intentionally match the high-level method taxonomy used by
:mod:`app.services.insight_explanation` so governance decisions can be surfaced
in insight explainability without creating a second taxonomy.
"""


@dataclass
class GovernanceDecision:
    requested_method: str
    allowed: bool
    effective_method: str
    fallback_used: bool
    policy_version: int
    reason_code: str
    user_message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_explanation_dict(self) -> dict[str, Any]:
        return {
            "requestedMethod": self.requested_method,
            "effectiveMethod": self.effective_method,
            "decision": "allowed" if self.allowed else ("fallback" if self.fallback_used else "blocked"),
            "policyVersion": self.policy_version,
            "message": self.user_message,
            "evaluatedAt": _now_iso(),
        }


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


class AIGovernanceService:
    """Central policy evaluator and administrator for tenant AI governance."""

    def __init__(self) -> None:
        # (tenant_id, version) -> effective policy dict
        self._cache: dict[tuple[int, int], dict[str, Any]] = {}

    def invalidate_cache(self, tenant_id: int | None = None) -> None:
        if tenant_id is None:
            self._cache.clear()
            return
        keys = [k for k in self._cache if k[0] == tenant_id]
        for key in keys:
            self._cache.pop(key, None)

    async def get_effective_policy(
        self, session: AsyncSession, tenant_id: int
    ) -> dict[str, Any]:
        """Return the merged default + tenant-override policy for a tenant."""
        policy_row = await session.scalar(
            select(TenantAIGovernancePolicy).where(
                TenantAIGovernancePolicy.tenant_id == tenant_id,
                TenantAIGovernancePolicy.is_active.is_(True),
            )
        )
        version = policy_row.version if policy_row else 0
        cache_key = (tenant_id, version)
        if cache_key in self._cache:
            return self._cache[cache_key]

        overrides: dict[str, dict[str, Any]] = {}
        if policy_row:
            method_rows = await session.scalars(
                select(TenantAIMethodPolicy).where(
                    TenantAIMethodPolicy.tenant_id == tenant_id,
                    TenantAIMethodPolicy.policy_id == policy_row.id,
                )
            )
            for row in method_rows:
                overrides[row.method_key] = {
                    "enabled": row.enabled,
                    "reason": row.reason,
                    "updated_by": row.updated_by,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                }

        methods: dict[str, Any] = {}
        for definition in METHOD_REGISTRY:
            override = overrides.get(definition.key)
            methods[definition.key] = {
                "key": definition.key,
                "displayName": definition.display_name,
                "description": definition.description,
                "category": definition.category,
                "riskLevel": definition.risk_level,
                "requiresSql": definition.requires_sql,
                "experimental": definition.experimental,
                "enabled": override["enabled"] if override else definition.default_enabled,
                "source": "tenant_override" if override else "default",
                "reason": override.get("reason") if override else None,
                "updatedBy": override.get("updated_by") if override else None,
                "updatedAt": override.get("updated_at") if override else None,
            }

        result: dict[str, Any] = {
            "tenantId": tenant_id,
            "version": version,
            "isDefault": policy_row is None,
            "methods": methods,
        }
        self._cache[cache_key] = result
        return result

    async def _ensure_policy(
        self, session: AsyncSession, tenant_id: int, user_id: int
    ) -> TenantAIGovernancePolicy:
        policy = await session.scalar(
            select(TenantAIGovernancePolicy).where(
                TenantAIGovernancePolicy.tenant_id == tenant_id
            )
        )
        if policy is None:
            policy = TenantAIGovernancePolicy(
                tenant_id=tenant_id,
                version=0,
                is_active=True,
                created_by=user_id,
                updated_by=user_id,
            )
            session.add(policy)
            await session.flush()
            for definition in METHOD_REGISTRY:
                session.add(
                    TenantAIMethodPolicy(
                        policy_id=policy.id,
                        tenant_id=tenant_id,
                        method_key=definition.key,
                        enabled=definition.default_enabled,
                        updated_by=user_id,
                    )
                )
            await session.flush()
        return policy

    async def evaluate_method(
        self,
        session: AsyncSession,
        tenant_id: int,
        requested_method: str,
        *,
        project_id: int | None = None,
        conversation_id: int | None = None,
        turn_id: int | None = None,
        insight_id: str | None = None,
        request_id: str | None = None,
        record: bool = True,
        actor_user_id: int | None = None,
    ) -> GovernanceDecision:
        """Evaluate a requested analytical method against tenant policy."""
        key = requested_method if requested_method in _METHOD_BY_KEY else "other"
        if key == "other" and requested_method != "other":
            # Try to normalise a legacy/unknown key to a registered one.
            mapped = infer_governance_key(insight_type=requested_method)
            if mapped != "other":
                key = mapped

        definition = _METHOD_BY_KEY[key]
        policy = await self.get_effective_policy(session, tenant_id)
        policy_version = policy["version"]
        method_state = policy["methods"][key]

        if method_state["enabled"]:
            decision = GovernanceDecision(
                requested_method=requested_method,
                allowed=True,
                effective_method=key,
                fallback_used=False,
                policy_version=policy_version,
                reason_code="method_allowed",
                user_message=f"{definition.display_name} is permitted by your organization's AI governance policy.",
            )
            if record:
                await self._record(
                    session,
                    tenant_id=tenant_id,
                    event_type="ai_governance.method_allowed",
                    method_key=key,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    insight_id=insight_id,
                    policy_version=policy_version,
                    decision="allowed",
                    reason_code="method_allowed",
                    details={"requested_method": requested_method},
                    request_id=request_id,
                    actor_user_id=actor_user_id,
                    actor_type="system",
                )
            return decision

        # Method is disabled; attempt fallback.
        for fallback in definition.fallback_method_keys:
            fallback_state = policy["methods"].get(fallback)
            if fallback_state and fallback_state["enabled"]:
                fallback_def = _METHOD_BY_KEY[fallback]
                decision = GovernanceDecision(
                    requested_method=requested_method,
                    allowed=True,
                    effective_method=fallback,
                    fallback_used=True,
                    policy_version=policy_version,
                    reason_code="method_disabled_fallback_available",
                    user_message=(
                        f"{definition.display_name} is disabled by your organization's AI governance policy. "
                        f"{fallback_def.display_name} was used instead."
                    ),
                    details={"fallback_from": key, "fallback_to": fallback},
                )
                if record:
                    await self._record(
                        session,
                        tenant_id=tenant_id,
                        event_type="ai_governance.method_fallback_used",
                        method_key=key,
                        project_id=project_id,
                        conversation_id=conversation_id,
                        turn_id=turn_id,
                        insight_id=insight_id,
                        policy_version=policy_version,
                        decision="fallback",
                        reason_code="method_disabled_fallback_available",
                        details={
                            "requested_method": requested_method,
                            "fallback_method": fallback,
                        },
                        request_id=request_id,
                        actor_user_id=actor_user_id,
                        actor_type="system",
                    )
                return decision

        decision = GovernanceDecision(
            requested_method=requested_method,
            allowed=False,
            effective_method="",
            fallback_used=False,
            policy_version=policy_version,
            reason_code="method_disabled_no_valid_fallback",
            user_message=(
                f"{definition.display_name} is disabled by your organization's AI governance policy. "
                "No permitted alternative is available for this request."
            ),
            details={"blocked_method": key},
        )
        if record:
            await self._record(
                session,
                tenant_id=tenant_id,
                event_type="ai_governance.method_blocked",
                method_key=key,
                project_id=project_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                insight_id=insight_id,
                policy_version=policy_version,
                decision="blocked",
                reason_code="method_disabled_no_valid_fallback",
                details={"requested_method": requested_method},
                request_id=request_id,
                actor_user_id=actor_user_id,
                actor_type="system",
            )
        return decision

    async def update_method_policy(
        self,
        session: AsyncSession,
        tenant_id: int,
        user_id: int,
        method_key: str,
        enabled: bool,
        reason: str | None,
        expected_version: int,
    ) -> dict[str, Any]:
        """Update a single method's enabled state with optimistic concurrency."""
        if method_key not in _METHOD_BY_KEY:
            raise ValueError(f"Unknown analytical method: {method_key}")
        policy = await self._ensure_policy(session, tenant_id, user_id)
        if policy.version != expected_version:
            raise PolicyVersionConflict(policy.version)

        method = await session.scalar(
            select(TenantAIMethodPolicy).where(
                TenantAIMethodPolicy.tenant_id == tenant_id,
                TenantAIMethodPolicy.policy_id == policy.id,
                TenantAIMethodPolicy.method_key == method_key,
            )
        )
        if method is None:
            method = TenantAIMethodPolicy(
                policy_id=policy.id,
                tenant_id=tenant_id,
                method_key=method_key,
                enabled=enabled,
                updated_by=user_id,
            )
            session.add(method)
            previous = {"enabled": _METHOD_BY_KEY[method_key].default_enabled}
        else:
            previous = {"enabled": method.enabled}
            method.enabled = enabled
            method.updated_by = user_id

        if reason is not None:
            method.reason = reason[:1000] if reason else None

        policy.version += 1
        policy.updated_by = user_id
        await session.flush()

        await self._record(
            session,
            tenant_id=tenant_id,
            event_type="ai_governance.method_enabled" if enabled else "ai_governance.method_disabled",
            method_key=method_key,
            policy_version=policy.version,
            decision="changed",
            reason_code="admin_override",
            previous_value=previous,
            new_value={"enabled": enabled, "reason": reason},
            actor_user_id=user_id,
            actor_type="user",
        )
        self.invalidate_cache(tenant_id)

        return await self.get_effective_policy(session, tenant_id)

    async def bulk_update_method_policy(
        self,
        session: AsyncSession,
        tenant_id: int,
        user_id: int,
        methods: list[dict[str, Any]],
        expected_version: int,
    ) -> dict[str, Any]:
        """Update many method states in one transaction."""
        policy = await self._ensure_policy(session, tenant_id, user_id)
        if policy.version != expected_version:
            raise PolicyVersionConflict(policy.version)

        for item in methods:
            method_key = item["method_key"]
            enabled = item["enabled"]
            reason = item.get("reason")
            if method_key not in _METHOD_BY_KEY:
                raise ValueError(f"Unknown analytical method: {method_key}")
            method = await session.scalar(
                select(TenantAIMethodPolicy).where(
                    TenantAIMethodPolicy.tenant_id == tenant_id,
                    TenantAIMethodPolicy.policy_id == policy.id,
                    TenantAIMethodPolicy.method_key == method_key,
                )
            )
            if method is None:
                method = TenantAIMethodPolicy(
                    policy_id=policy.id,
                    tenant_id=tenant_id,
                    method_key=method_key,
                    enabled=enabled,
                    updated_by=user_id,
                )
                session.add(method)
                previous = {"enabled": _METHOD_BY_KEY[method_key].default_enabled}
            else:
                previous = {"enabled": method.enabled}
                method.enabled = enabled
                method.updated_by = user_id
            if reason is not None:
                method.reason = reason[:1000] if reason else None
            await self._record(
                session,
                tenant_id=tenant_id,
                event_type="ai_governance.method_enabled" if enabled else "ai_governance.method_disabled",
                method_key=method_key,
                policy_version=policy.version,
                decision="changed",
                reason_code="admin_bulk_override",
                previous_value=previous,
                new_value={"enabled": enabled, "reason": reason},
                actor_user_id=user_id,
                actor_type="user",
            )

        policy.version += 1
        policy.updated_by = user_id
        await session.flush()

        await self._record(
            session,
            tenant_id=tenant_id,
            event_type="ai_governance.policy_bulk_updated",
            policy_version=policy.version,
            decision="changed",
            reason_code="admin_bulk_override",
            new_value={"method_count": len(methods)},
            actor_user_id=user_id,
            actor_type="user",
        )
        self.invalidate_cache(tenant_id)

        return await self.get_effective_policy(session, tenant_id)

    async def list_audit_events(
        self,
        session: AsyncSession,
        tenant_id: int,
        *,
        event_type: str | None = None,
        method_key: str | None = None,
        actor_user_id: int | None = None,
        decision: str | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return a paginated, filtered list of governance audit events."""
        stmt = select(AIGovernanceAuditEvent).where(
            AIGovernanceAuditEvent.tenant_id == tenant_id
        )
        if event_type:
            stmt = stmt.where(AIGovernanceAuditEvent.event_type == event_type)
        if method_key:
            stmt = stmt.where(AIGovernanceAuditEvent.method_key == method_key)
        if actor_user_id is not None:
            stmt = stmt.where(AIGovernanceAuditEvent.actor_user_id == actor_user_id)
        if decision:
            stmt = stmt.where(AIGovernanceAuditEvent.decision == decision)
        if start:
            stmt = stmt.where(AIGovernanceAuditEvent.created_at >= start)
        if end:
            stmt = stmt.where(AIGovernanceAuditEvent.created_at <= end)

        total = await session.scalar(
            select(func.count())
            .select_from(AIGovernanceAuditEvent)
            .where(AIGovernanceAuditEvent.tenant_id == tenant_id)
        )
        stmt = stmt.order_by(AIGovernanceAuditEvent.created_at.desc()).limit(limit).offset(offset)
        rows = (await session.scalars(stmt)).all()
        return {
            "total": total or 0,
            "limit": limit,
            "offset": offset,
            "events": [
                {
                    "id": row.id,
                    "tenant_id": row.tenant_id,
                    "actor_user_id": row.actor_user_id,
                    "actor_type": row.actor_type,
                    "event_type": row.event_type,
                    "method_key": row.method_key,
                    "project_id": row.project_id,
                    "conversation_id": row.conversation_id,
                    "turn_id": row.turn_id,
                    "insight_id": row.insight_id,
                    "policy_version": row.policy_version,
                    "previous_value": row.previous_value,
                    "new_value": row.new_value,
                    "decision": row.decision,
                    "reason_code": row.reason_code,
                    "details": row.details,
                    "request_id": row.request_id,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ],
        }

    async def _record(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        event_type: str,
        actor_user_id: int | None = None,
        actor_type: str = "system",
        method_key: str | None = None,
        project_id: int | None = None,
        conversation_id: int | None = None,
        turn_id: int | None = None,
        insight_id: str | None = None,
        policy_version: int | None = None,
        previous_value: dict[str, Any] | None = None,
        new_value: dict[str, Any] | None = None,
        decision: str | None = None,
        reason_code: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        try:
            event = AIGovernanceAuditEvent(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                actor_type=actor_type,
                event_type=event_type,
                method_key=method_key,
                project_id=project_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                insight_id=insight_id,
                policy_version=policy_version,
                previous_value=previous_value,
                new_value=new_value,
                decision=decision,
                reason_code=reason_code,
                details=details,
                request_id=request_id,
            )
            session.add(event)
            await session.flush()
        except Exception as exc:
            logger.warning("AI governance audit record failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass


class PolicyVersionConflict(Exception):
    """Raised when an admin update is based on a stale policy version."""

    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__(f"Policy version conflict; current version is {current_version}")


# Global singleton for runtime use.  Tests can instantiate their own.
ai_governance_service = AIGovernanceService()
