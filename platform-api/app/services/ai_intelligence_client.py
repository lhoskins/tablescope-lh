"""Signed client for the AI server's intelligence endpoints.

Wraps the HMAC-signed POST to ``/ai/intelligence/plan`` and
``/ai/intelligence/interpret``. Kept separate from the route layer so the
home-intelligence service can drive the plan -> execute -> interpret loop
without importing route modules (avoids circular imports).

Disabled AI returns ``None`` so callers can degrade cleanly. Transport, timeout,
HTTP, and malformed-response failures raise :class:`AIUnavailableError` so
streaming callers can report an honest error instead of a misleading empty result.
"""

from __future__ import annotations

import asyncio
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
_BUSY_MAX_ATTEMPTS = 3
_BUSY_DEFAULT_RETRY_SECONDS = 5.0
_BUSY_MAX_RETRY_SECONDS = 30.0


class AIUnavailableError(RuntimeError):
    """The enabled AI service could not complete a request.

    ``retryable`` distinguishes transient capacity/contention failures (gate
    ``503`` busy, timeouts, transport drops) from terminal ones (other HTTP
    errors, malformed responses). The durable Home-intelligence worker maps a
    retryable error onto ``arq``'s ``Retry`` — so contention defers a project
    instead of dropping it — while a terminal error is reported once and not
    retried. ``retry_after`` carries the server's ``Retry-After`` when present.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        # Default: only an explicit 503 "busy" is retryable; callers pass
        # ``retryable=True`` for timeout/transport failures.
        self.retryable = (status_code == 503) if retryable is None else retryable


def _sign_payload(payload: dict[str, Any], secret: str) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def is_enabled() -> bool:
    settings = get_settings()
    return bool(settings.tablescope_ai_enabled and settings.tablescope_ai_api_url)


def _retry_seconds(
    *,
    attempt: int,
    base_seconds: float,
    response: httpx.Response | None = None,
) -> float:
    if response is not None:
        raw = response.headers.get("Retry-After")
        if raw:
            try:
                return min(max(float(raw), 0.0), _BUSY_MAX_RETRY_SECONDS)
            except ValueError:
                pass
    return min(
        max(base_seconds, 0.0) * (2 ** max(attempt - 1, 0)),
        _BUSY_MAX_RETRY_SECONDS,
    )


async def _post(
    path: str,
    payload: dict[str, Any],
    *,
    max_attempts: int = _BUSY_MAX_ATTEMPTS,
    retry_read_timeouts: bool = False,
    retry_base_seconds: float = _BUSY_DEFAULT_RETRY_SECONDS,
) -> dict[str, Any] | None:
    settings = get_settings()
    if not is_enabled():
        return None
    base_payload = dict(payload)
    url = f"{settings.tablescope_ai_api_url}{path}"

    attempts = max(1, max_attempts)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for attempt in range(1, attempts + 1):
            signed_payload = dict(base_payload)
            signed_payload["timestamp"] = time.time()
            signed_payload["signature"] = _sign_payload(
                signed_payload, settings.tablescope_ai_signing_secret
            )
            try:
                resp = await client.post(url, json=signed_payload)
            except httpx.ReadTimeout as exc:
                if retry_read_timeouts and attempt < attempts:
                    retry_seconds = _retry_seconds(
                        attempt=attempt,
                        base_seconds=retry_base_seconds,
                    )
                    logger.warning(
                        "AI intelligence call to %s timed out; retrying in %.1fs "
                        "(attempt %s/%s)",
                        path,
                        retry_seconds,
                        attempt,
                        attempts,
                    )
                    await asyncio.sleep(retry_seconds)
                    continue
                logger.warning("AI intelligence call to %s timed out: %s", path, exc)
                raise AIUnavailableError(
                    "AI server timed out; retry shortly.", retryable=True
                ) from exc
            except httpx.TimeoutException as exc:
                logger.warning("AI intelligence call to %s timed out: %s", path, exc)
                raise AIUnavailableError(
                    "AI server timed out; retry shortly.", retryable=True
                ) from exc
            except httpx.TransportError as exc:
                logger.warning("AI intelligence transport failure for %s: %s", path, exc)
                raise AIUnavailableError(
                    "AI server is unavailable; retry shortly.", retryable=True
                ) from exc

            if resp.status_code == 503 and attempt < attempts:
                retry_seconds = _retry_seconds(
                    attempt=attempt,
                    base_seconds=retry_base_seconds,
                    response=resp,
                )
                logger.warning(
                    "AI intelligence server busy for %s; retrying in %.1fs "
                    "(attempt %s/%s)",
                    path,
                    retry_seconds,
                    attempt,
                    attempts,
                )
                await asyncio.sleep(retry_seconds)
                continue

            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                retry_after: float | None = None
                if status_code == 503:
                    message = "AI server is busy; retry shortly."
                    raw = exc.response.headers.get("Retry-After")
                    if raw:
                        try:
                            retry_after = min(
                                max(float(raw), 0.0), _BUSY_MAX_RETRY_SECONDS
                            )
                        except ValueError:
                            retry_after = None
                else:
                    message = f"AI server request failed with HTTP {status_code}."
                logger.warning("AI intelligence HTTP failure for %s: %s", path, exc)
                raise AIUnavailableError(
                    message, status_code=status_code, retry_after=retry_after
                ) from exc
            break

    try:
        data = resp.json()
    except ValueError as exc:
        logger.warning("AI intelligence returned invalid JSON for %s", path)
        raise AIUnavailableError("AI server returned an invalid response.") from exc
    if not isinstance(data, dict):
        raise AIUnavailableError("AI server returned an invalid response.")
    return data


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
    settings = get_settings()
    max_retries = max(0, settings.home_intelligence_plan_max_retries)
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
            "reference_kpis": [],
            "max_analyses": max_analyses,
            "granularity": granularity,
        },
        max_attempts=max_retries + 1,
        retry_read_timeouts=True,
        retry_base_seconds=max(
            0.0, settings.home_intelligence_plan_retry_base_seconds
        ),
    )
    if result is None:
        return None
    analyses = result.get("analyses")
    return analyses if isinstance(analyses, list) else []


async def project_insight(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    project: dict[str, Any],
    tables: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    dashboards: list[dict[str, Any]],
    kpis: list[str],
    knowledge_graph_context: dict[str, Any] | None = None,
    recent_activity: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Ask the AI server for the project-scoped Project Insight report.

    Returns the structured contract (executiveSummary, questionsToAsk,
    trendDetection, recommendedDashboards/Queries/Kpis,
    insightValidationWorkflow), or ``None`` if the AI server is unavailable so
    the caller can degrade gracefully.
    """
    result = await _post(
        "/ai/intelligence/project-insight",
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "project": project,
            "tables": tables,
            "documents": documents,
            "queries": queries,
            "dashboards": dashboards,
            "kpis": kpis,
            "knowledge_graph_context": knowledge_graph_context or {},
            "recent_activity": recent_activity or {},
        },
    )
    return result if isinstance(result, dict) else None


async def knowledge_graph_cards(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    lens: str,
    center: dict[str, Any],
    neighbors: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    kpis: list[str],
    max_cards: int = 8,
) -> list[dict[str, Any]] | None:
    """Ask the LLM for Knowledge-Graph insight cards for the selected node.

    Returns the raw card dicts, or ``None`` when the AI server is unavailable so
    the caller can fall back to the deterministic cards.
    """
    result = await _post(
        "/ai/intelligence/knowledge-graph",
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "lens": lens,
            "center": center,
            "neighbors": neighbors,
            "documents": documents,
            "kpis": kpis,
            "max_cards": max_cards,
        },
    )
    if result is None:
        return None
    cards = result.get("cards")
    return cards if isinstance(cards, list) else []


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
