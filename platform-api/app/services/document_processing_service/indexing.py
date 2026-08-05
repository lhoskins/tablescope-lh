
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from app.config import get_settings

from .profiling import logger


async def _index_document_vectors(
    tenant_id: int,
    user_id: int,
    project_id: int,
    document_id: int,
    source_id: int,
    visibility: str,
    content: str,
) -> None:
    """Embed and index the document text into the tenant vector store for AI Ask.

    Lets users ask detailed, passage-level questions about the document via
    semantic retrieval, not just summary-level questions.
    """
    settings = get_settings()
    if not settings.tablescope_ai_enabled or not settings.tablescope_ai_api_url:
        return
    if not content.strip():
        return

    ai_url = settings.tablescope_ai_api_url

    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "project_id": project_id,
        "document_id": document_id,
        "source_type": "project_asset",
        "source_id": source_id,
        "file_path": "",
        "content": content,
        "visibility": visibility or "shared_project",
        "timestamp": time.time(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["signature"] = hmac.new(
        settings.tablescope_ai_signing_secret.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()

    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(f"{ai_url}/ai/index/document", json=payload)
    if resp.status_code != 200:
        logger.warning(
            "Vector indexing returned HTTP %d for document %d: %s",
            resp.status_code, document_id, resp.text[:200],
        )
