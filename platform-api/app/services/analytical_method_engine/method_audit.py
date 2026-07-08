"""Audit logging for the Method Engine.

Writes a ``method_catalog_audit_log`` row for every selection / rejection /
fallback so any analytical answer is traceable back to the catalog version and
method id. Failures here never propagate — auditing must not break analysis.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytical_method_catalog import MethodCatalogAuditLog

logger = logging.getLogger(__name__)


async def record(
    session: AsyncSession,
    *,
    tenant_id: int | None,
    event_type: str,
    analysis_intent: str | None,
    selected_method: str | None,
    rejected_methods: list[str] | None,
    envelope: dict[str, Any] | None,
    registry_version: int | None,
    reason: str | None = None,
) -> None:
    try:
        session.add(
            MethodCatalogAuditLog(
                tenant_id=tenant_id,
                catalog_version_id=registry_version,
                method_id=selected_method,
                event_type=event_type,
                analysis_intent=analysis_intent,
                selected_method=selected_method,
                rejected_methods=rejected_methods or [],
                envelope=envelope,
                reason=reason,
            )
        )
        await session.commit()
    except Exception as exc:
        logger.warning("Method audit log failed: %s", exc)
        try:
            await session.rollback()
        except Exception:
            pass
