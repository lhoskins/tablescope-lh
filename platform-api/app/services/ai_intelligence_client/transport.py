
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

from app.config import get_settings as get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(900.0, connect=10.0)
_BUSY_MAX_ATTEMPTS = 3
_BUSY_DEFAULT_RETRY_SECONDS = 5.0
_BUSY_MAX_RETRY_SECONDS = 30.0

# Bounded concurrency for chat-style SQL generation and prose answers.
# These calls must remain responsive while the KG precache pipeline fans out
# plan/fix/interpret work, so they share a separate gate from the per-project
# home-intelligence semaphore.
_CHAT_MAX_CONCURRENT = 4
_chat_semaphore: asyncio.Semaphore | None = None


class AIUnavailableError(RuntimeError):
    """The enabled AI service could not complete a request.

    ``retryable`` distinguishes transient capacity/contention failures (gate
    ``503`` busy, timeouts, transport drops) from terminal ones (other HTTP
    errors, malformed responses). The durable Home-intelligence worker maps a
    retryable error onto ``arq``'s ``Retry`` — so contention defers a project
    instead of dropping it — while a terminal error is reported once and not
    retried. ``retry_after`` carries the server's ``Retry-After`` when present.

    ``declined`` distinguishes a second, unrelated axis from ``retryable``: it
    is true when the AI server was reached and responded, but rejected this
    specific request (a 4xx like the SQL generator's structured 422 "needs
    clarification") -- as opposed to a genuine outage (unreachable, timed
    out, or busy). Both raise this same exception type so every call site
    keeps its "no silent fallback" guarantee, but a declined request has a
    real, often structured ``detail`` worth surfacing to the user instead of
    a generic "the AI service is unavailable" -- which is simply false when
    the server answered.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool | None = None,
        retry_after: float | None = None,
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.detail = detail
        # Default: only an explicit 503 "busy" is retryable; callers pass
        # ``retryable=True`` for timeout/transport failures.
        self.retryable = (status_code == 503) if retryable is None else retryable

    @property
    def declined(self) -> bool:
        """True when the AI server responded but rejected this request (4xx,
        excluding 503 busy -- that's a capacity signal, not a rejection)."""
        return self.status_code is not None and 400 <= self.status_code < 500


def _sign_payload(payload: dict[str, Any], secret: str) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def is_enabled() -> bool:
    import app.services.ai_intelligence_client as _aic

    settings = _aic.get_settings()
    return bool(settings.tablescope_ai_enabled and settings.tablescope_ai_api_url)


def _chat_sem() -> asyncio.Semaphore:
    """Lazy chat-call semaphore to avoid creating it at import time."""
    global _chat_semaphore
    if _chat_semaphore is None:
        _chat_semaphore = asyncio.Semaphore(_CHAT_MAX_CONCURRENT)
    return _chat_semaphore


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
    import app.services.ai_intelligence_client as _aic

    if not _aic.is_enabled():
        return None
    settings = _aic.get_settings()
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
            body = json.dumps(signed_payload, default=str, ensure_ascii=False)
            try:
                resp = await client.post(
                    url,
                    content=body.encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
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
                    "AI server timed out; retry shortly.", retryable=False
                ) from exc
            except httpx.TimeoutException as exc:
                logger.warning("AI intelligence call to %s timed out: %s", path, exc)
                raise AIUnavailableError(
                    "AI server timed out; retry shortly.", retryable=False
                ) from exc
            except httpx.TransportError as exc:
                logger.warning("AI intelligence transport failure for %s: %s", path, exc)
                raise AIUnavailableError(
                    "AI server is unavailable; retry shortly.", retryable=False
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
                # A 4xx body is usually FastAPI's {"detail": ...} envelope
                # around the AI server's own structured rejection (e.g. the
                # SQL generator's {"code": "needs_clarification", "reason":
                # ..., "suggested_sources": [...]}) -- unwrap it so a caller
                # can build an accurate, specific message instead of a
                # generic one.
                try:
                    error_body = exc.response.json()
                    detail: Any = (
                        error_body.get("detail", error_body)
                        if isinstance(error_body, dict)
                        else error_body
                    )
                except ValueError:
                    detail = exc.response.text[:1000] or None
                raise AIUnavailableError(
                    message,
                    status_code=status_code,
                    retry_after=retry_after,
                    detail=detail,
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
