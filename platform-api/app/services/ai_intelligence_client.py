"""Signed client for the AI server's intelligence endpoints.

Wraps the HMAC-signed POST to ``/ai/intelligence/plan`` and
``/ai/intelligence/interpret``. Kept separate from the route layer so the
home-intelligence service can drive the plan -> execute -> interpret loop
without importing route modules (avoids circular imports).

Every call returns ``None`` on any failure (AI disabled, unreachable, bad
response) so callers can fall back deterministically — the feature never breaks
just because the AI server is slow or down.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


def _sign_payload(payload: dict[str, Any], secret: str) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def is_enabled() -> bool:
    settings = get_settings()
    return bool(settings.tablescope_ai_enabled and settings.tablescope_ai_api_url)


async def _post(path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    settings = get_settings()
    if not is_enabled():
        return None
    payload = dict(payload)
    payload["timestamp"] = time.time()
    payload["signature"] = _sign_payload(payload, settings.tablescope_ai_signing_secret)
    url = f"{settings.tablescope_ai_api_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        # Degrade gracefully on any AI failure (disabled/unreachable/bad response).
        logger.warning("AI intelligence call to %s failed: %s", path, exc)
        return None


async def plan(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    allowed_tables: list[str],
    documents: list[dict[str, Any]],
    table_schema: list[dict[str, Any]] | None = None,
    relationship_hints: list[dict[str, Any]] | None = None,
    max_analyses: int = 6,
    granularity: int = 3,
) -> list[dict[str, Any]] | None:
    """Ask the LLM to propose diagnostic analyses. Returns ``analyses`` or None."""
    result = await _post(
        "/ai/intelligence/plan",
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "allowed_tables": allowed_tables,
            "table_schema": table_schema or [],
            "documents": documents,
            "relationship_hints": relationship_hints or [],
            "max_analyses": max_analyses,
            "granularity": granularity,
        },
    )
    if result is None:
        return None
    analyses = result.get("analyses")
    return analyses if isinstance(analyses, list) else []


async def fix_sql(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    sql: str,
    error: str,
    allowed_tables: list[str],
    table_schema: list[dict[str, Any]] | None = None,
) -> str | None:
    """Ask the LLM to repair a query that the engine rejected.

    Returns a corrected SQL string, or None if the AI is unavailable or
    declines to fix it.
    """
    result = await _post(
        "/ai/intelligence/fix-sql",
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "sql": sql,
            "error": error,
            "allowed_tables": allowed_tables,
            "table_schema": table_schema or [],
        },
    )
    if result is None:
        return None
    fixed = result.get("sql")
    return fixed if isinstance(fixed, str) and fixed.strip() else None


async def interpret(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    analyses: list[dict[str, Any]],
) -> dict[str, dict[str, Any]] | None:
    """Turn executed results into prose. Returns ``{analysis_id: insight}`` or None."""
    if not analyses:
        return {}
    result = await _post(
        "/ai/intelligence/interpret",
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "analyses": analyses,
        },
    )
    if result is None:
        return None
    out: dict[str, dict[str, Any]] = {}
    for ins in result.get("insights", []):
        if isinstance(ins, dict) and ins.get("id"):
            out[str(ins["id"])] = ins
    return out
