"""Signed client for the AI server's reference-library endpoints.

Reuses the HMAC-signed POST helper from :mod:`ai_intelligence_client` so the
signature scheme stays identical across all AI server calls.
"""

from __future__ import annotations

import logging

from app.services.ai_intelligence_client import _post, is_enabled

logger = logging.getLogger(__name__)

__all__ = ["is_enabled", "summarize_reference_document", "suggest_references"]


async def summarize_reference_document(
    *,
    tenant_id: int,
    user_id: int,
    document_id: int,
    title: str,
    issuing_body: str,
    domain_tag: str,
    extracted_text: str,
) -> str | None:
    """Return a 2-4 sentence AI grounding summary, or None if unavailable."""
    result = await _post(
        "/ai/reference-library/summarize",
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": 0,
            "document_id": document_id,
            "title": title,
            "issuing_body": issuing_body,
            "domain_tag": domain_tag,
            "extracted_text": extracted_text,
        },
    )
    if result is None:
        return None
    summary = result.get("summary")
    return summary if isinstance(summary, str) and summary.strip() else None


async def suggest_references(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    data_source_types: list[str],
    table_names: list[str],
    document_types: list[str],
    recent_query_topics: list[str],
    candidate_domains: list[str],
) -> list[dict] | None:
    """Return [{domainTag, reasoning}] suggestions, or None if unavailable."""
    result = await _post(
        "/ai/reference-library/suggest",
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "data_source_types": data_source_types,
            "table_names": table_names,
            "document_types": document_types,
            "recent_query_topics": recent_query_topics,
            "candidate_domains": candidate_domains,
        },
    )
    if result is None:
        return None
    suggestions = result.get("suggestions")
    return suggestions if isinstance(suggestions, list) else []
