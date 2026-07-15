"""Tenant AI governance policy service.

Provides an authoritative registry of governable analytical methods, per-tenant
policy evaluation, administrative updates, and an append-only audit log.

The registry keys intentionally match the high-level method taxonomy used by
:mod:`app.services.insight_explanation` so governance decisions can be surfaced
in insight explainability without creating a second taxonomy.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_governance_audit import AIGovernanceAuditEvent
from app.models.tenant_ai_governance import (
    TenantAIGovernancePolicy,
    TenantAIMethodPolicy,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalyticalMethodDefinition:
    key: str
    display_name: str
    description: str
    category: str
    risk_level: str
    supports_fallback: bool
    fallback_method_keys: tuple[str, ...]
    default_enabled: bool
    requires_sql: bool
    experimental: bool = False
    # Heuristic patterns that map lower-level catalog method_ids / intents to
    # this governance key.  These are used when a component only knows the
    # statistical method selected by the Method Engine.
    catalog_method_patterns: tuple[str, ...] = ()
    intent_patterns: tuple[str, ...] = ()


METHOD_REGISTRY: tuple[AnalyticalMethodDefinition, ...] = (
    AnalyticalMethodDefinition(
        key="aggregation",
        display_name="Aggregation",
        description="Summarize values with counts, sums, averages, or other rollups.",
        category="descriptive",
        risk_level="low",
        supports_fallback=False,
        fallback_method_keys=(),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("sum", "count", "mean", "average", "aggregation", "group_by"),
        intent_patterns=("describe_numeric", "compare_to_target", "total"),
    ),
    AnalyticalMethodDefinition(
        key="trend_analysis",
        display_name="Trend analysis",
        description="Identify direction and rate of change over ordered time.",
        category="diagnostic",
        risk_level="low",
        supports_fallback=True,
        fallback_method_keys=("aggregation", "distribution_analysis"),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("trend", "slope", "mann_kendall", "sens"),
        intent_patterns=("detect_trend", "trend"),
    ),
    AnalyticalMethodDefinition(
        key="period_over_period_comparison",
        display_name="Period-over-period comparison",
        description="Compare a metric across two or more time periods.",
        category="comparative",
        risk_level="low",
        supports_fallback=True,
        fallback_method_keys=("trend_analysis", "aggregation"),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("period", "yoy", "year_over_year", "pop"),
        intent_patterns=("compare", "period"),
    ),
    AnalyticalMethodDefinition(
        key="variance_analysis",
        display_name="Variance analysis",
        description="Measure and explain differences between groups or against a target.",
        category="comparative",
        risk_level="medium",
        supports_fallback=True,
        fallback_method_keys=("aggregation", "distribution_analysis"),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("anova", "variance", "welch", "kruskal", "mann_whitney", "t_test"),
        intent_patterns=("compare_two_groups", "compare_multiple_groups", "compare_paired", "compare_to_target"),
    ),
    AnalyticalMethodDefinition(
        key="ranking",
        display_name="Ranking",
        description="Order entities by a metric and surface top or bottom performers.",
        category="descriptive",
        risk_level="low",
        supports_fallback=False,
        fallback_method_keys=(),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("rank", "top", "bottom"),
        intent_patterns=("rank", "top", "bottom"),
    ),
    AnalyticalMethodDefinition(
        key="segmentation",
        display_name="Segmentation",
        description="Divide data into meaningful groups for comparison.",
        category="diagnostic",
        risk_level="low",
        supports_fallback=True,
        fallback_method_keys=("distribution_analysis", "aggregation"),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("segment", "cluster", "group"),
        intent_patterns=("segment", "group_by", "breakdown"),
    ),
    AnalyticalMethodDefinition(
        key="anomaly_detection",
        display_name="Anomaly detection",
        description="Flag values or patterns that deviate markedly from the norm.",
        category="diagnostic",
        risk_level="medium",
        supports_fallback=True,
        fallback_method_keys=("distribution_analysis", "ranking"),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("anomaly", "outlier", "iqr", "z_score"),
        intent_patterns=("anomaly", "outlier"),
    ),
    AnalyticalMethodDefinition(
        key="distribution_analysis",
        display_name="Distribution analysis",
        description="Describe the shape, spread, and frequency of values.",
        category="descriptive",
        risk_level="low",
        supports_fallback=False,
        fallback_method_keys=(),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("distribution", "histogram", "normality", "shapiro", "anderson", "goodness"),
        intent_patterns=("normality", "distribution"),
    ),
    AnalyticalMethodDefinition(
        key="correlation_analysis",
        display_name="Correlation analysis",
        description="Measure statistical association between two or more variables.",
        category="diagnostic",
        risk_level="medium",
        supports_fallback=True,
        fallback_method_keys=("distribution_analysis", "aggregation"),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("correlation", "pearson", "spearman", "kendall", "mutual_information"),
        intent_patterns=("relationship_numeric", "relationship_monotonic", "correlation"),
    ),
    AnalyticalMethodDefinition(
        key="forecast",
        display_name="Forecast",
        description="Project future values from historical patterns.",
        category="predictive",
        risk_level="high",
        supports_fallback=True,
        fallback_method_keys=("trend_analysis", "period_over_period_comparison"),
        default_enabled=True,
        requires_sql=True,
        experimental=True,
        catalog_method_patterns=("forecast", "arima", "prophet", "exponential_smoothing"),
        intent_patterns=("forecast", "predict"),
    ),
    AnalyticalMethodDefinition(
        key="document_synthesis",
        display_name="Document synthesis",
        description="Synthesize an answer from project or reference documents without executable SQL.",
        category="document",
        risk_level="low",
        supports_fallback=False,
        fallback_method_keys=(),
        default_enabled=True,
        requires_sql=False,
        catalog_method_patterns=(),
        intent_patterns=("document", "policy", "synthesis"),
    ),
    AnalyticalMethodDefinition(
        key="rule_based_detection",
        display_name="Rule-based detection",
        description="Identify records that violate a threshold, SLA, or status rule.",
        category="rule-based",
        risk_level="low",
        supports_fallback=False,
        fallback_method_keys=(),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("threshold", "sla", "rule", "breach", "status"),
        intent_patterns=("rule", "threshold", "sla", "breach"),
    ),
    AnalyticalMethodDefinition(
        key="other",
        display_name="Other",
        description="An analytical approach not covered by the standard taxonomy.",
        category="other",
        risk_level="low",
        supports_fallback=False,
        fallback_method_keys=("aggregation",),
        default_enabled=True,
        requires_sql=False,
        catalog_method_patterns=(),
        intent_patterns=(),
    ),
)

_METHOD_BY_KEY: dict[str, AnalyticalMethodDefinition] = {m.key: m for m in METHOD_REGISTRY}

# Mapping from the built-in deterministic prompt types used by home intelligence.
_INSIGHT_TYPE_METHOD: dict[str, str] = {
    "risk_sla": "rule_based_detection",
    "risk_threshold": "rule_based_detection",
    "risk_expiry": "document_synthesis",
    "risk_upcoming": "trend_analysis",
    "trend_spend": "period_over_period_comparison",
    "trend_metric": "trend_analysis",
    "opportunity_supplier": "ranking",
    "opportunity_performance": "ranking",
    "opportunity_top_performer": "ranking",
}


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


def get_method_definition(key: str) -> AnalyticalMethodDefinition | None:
    return _METHOD_BY_KEY.get(key)


def get_method_label(key: str | None) -> str:
    return _METHOD_BY_KEY.get(key or "other", _METHOD_BY_KEY["other"]).display_name


def list_method_definitions() -> list[AnalyticalMethodDefinition]:
    return list(METHOD_REGISTRY)


def infer_governance_key(
    *,
    question: str | None = None,
    insight_type: str | None = None,
    chart_type: str | None = None,
    sql: str | None = None,
    documents: list[str] | None = None,
    category: str | None = None,
    method_id: str | None = None,
    analysis_intent: str | None = None,
) -> str:
    """Map available signals to a single governance method key."""
    q = (question or "").lower()
    if q:
        # Direct user phrasing takes precedence when the query is explicit.
        if "forecast" in q or "predict" in q:
            return "forecast"
        if re.search(r"\b(total|sum|average|mean|aggregat|amount)\b", q):
            return "aggregation"
        if re.search(r"\bcorrelat(?:e|ion)?\b", q):
            return "correlation_analysis"
        if re.search(r"\b(anomal(?:y|ies)|outlier(?:s)?)\b", q):
            return "anomaly_detection"
        if re.search(r"\b(?:variance|anova|t-test|significant difference)\b", q):
            return "variance_analysis"
        if re.search(r"\bsegment\b", q):
            return "segmentation"
        if re.search(r"\bcompare\b", q) and re.search(r"\bperiod|year|month|quarter\b", q):
            return "period_over_period_comparison"

    if method_id:
        mid = method_id.lower()
        for definition in METHOD_REGISTRY:
            for pattern in definition.catalog_method_patterns:
                if pattern in mid:
                    return definition.key

    if analysis_intent:
        intent = analysis_intent.lower()
        for definition in METHOD_REGISTRY:
            for pattern in definition.intent_patterns:
                if pattern in intent:
                    return definition.key

    if insight_type:
        exact = _INSIGHT_TYPE_METHOD.get(insight_type)
        if exact:
            return exact
        base = insight_type.split("_", 1)[0] if insight_type else ""
        if category == "relationship" or "relationship" in insight_type:
            return "correlation_analysis"
        if documents and not sql:
            return "document_synthesis"
        if chart_type in ("line", "area"):
            return "trend_analysis"
        if chart_type in ("bar", "radial_bar") and base == "opportunity":
            return "ranking"
        if chart_type == "bar" and (base == "risk" or "status" in insight_type):
            return "distribution_analysis"
        if chart_type == "kpi_grid" and base in ("trend", "spend"):
            return "period_over_period_comparison"
        if base == "risk":
            return "rule_based_detection"
        if base == "opportunity":
            return "ranking"
        if base == "trend":
            return "trend_analysis"

    if chart_type in ("line", "area"):
        return "trend_analysis"
    if chart_type in ("bar", "radial_bar"):
        return "ranking"
    if documents and not sql:
        return "document_synthesis"

    return "other"


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
