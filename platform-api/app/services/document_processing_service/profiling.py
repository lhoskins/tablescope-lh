
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


class DocumentProfileError(Exception):
    """Raised when the AI document profiler cannot produce a profile."""


def _hash_stored_file(storage_location: str | None) -> str | None:
    """SHA-256 of the file currently at the asset's storage location."""
    if not storage_location:
        return None
    try:
        with open(storage_location, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


async def call_document_profiler(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    asset_id: int,
    document_id: int | None,
    filename: str,
    asset_type: str,
    content_type: str,
    text_preview: str,
    chunks: list[dict],
    ref_tags: list[str],
    ref_kpis: list[str],
    include_family: bool = True,
) -> dict[str, Any]:
    """Scope-agnostic entrypoint to the shared AI document profiler.

    Used by both the project-asset pipeline and the tenant-wide reference
    libraries. ``include_family`` is the only scope-dependent knob: project
    documents request the project-scoped family block, tenant-wide libraries
    disable it so the family-classification step never runs for them.
    """
    return await _call_ai_profile(
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id,
        asset_id=asset_id,
        document_id=document_id,
        filename=filename,
        asset_type=asset_type,
        content_type=content_type,
        text_preview=text_preview,
        chunks=chunks,
        ref_tags=ref_tags,
        ref_kpis=ref_kpis,
        include_family=include_family,
    )


async def _call_ai_profile(
    tenant_id: int,
    user_id: int,
    project_id: int,
    asset_id: int,
    document_id: int | None,
    filename: str,
    asset_type: str,
    content_type: str,
    text_preview: str,
    chunks: list[dict],
    ref_tags: list[str],
    ref_kpis: list[str],
    include_family: bool = True,
) -> dict[str, Any]:
    """Call the AI server's dedicated document profiling endpoint.

    Raises DocumentProfileError on any failure. There is no /ai/ask fallback:
    the generic Q&A endpoint refuses extraction tasks, so a failure here must
    surface as a failed document rather than silently degrading.
    """
    settings = get_settings()
    if not settings.tablescope_ai_enabled or not settings.tablescope_ai_api_url:
        raise DocumentProfileError("AI is not configured (tablescope_ai_enabled / tablescope_ai_api_url)")

    ai_url = settings.tablescope_ai_api_url

    def _sign(p: dict[str, Any]) -> str:
        canonical = json.dumps(p, sort_keys=True, separators=(",", ":"))
        return hmac.new(
            settings.tablescope_ai_signing_secret.encode(),
            canonical.encode(),
            hashlib.sha256,
        ).hexdigest()

    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "project_id": project_id,
        "asset_id": asset_id,
        "document_id": document_id,
        "filename": filename,
        "asset_type": asset_type,
        "content_type": content_type,
        "text_preview": text_preview,
        "chunks": chunks,
        "enabled_reference_tags": ref_tags,
        "enabled_reference_kpis": ref_kpis,
        "include_family": include_family,
        "timestamp": time.time(),
    }
    payload["signature"] = _sign(payload)

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(f"{ai_url}/ai/document/profile", json=payload)
    except Exception as exc:
        raise DocumentProfileError(f"Could not reach AI document profiler: {exc}") from exc

    if resp.status_code != 200:
        raise DocumentProfileError(
            f"AI document profiler returned HTTP {resp.status_code}: {resp.text[:300]}"
        )

    return resp.json()
