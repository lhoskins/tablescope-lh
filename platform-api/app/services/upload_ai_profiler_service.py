"""Upload AI profiler — classifies uploaded files against the reference catalog.

After a file is uploaded, this service:
1. Collects schema + sample rows from the file profiler
2. Loads reference tags and KPIs for the tenant
3. Calls the AI to classify the file against the catalog
4. Persists tag/KPI suggestions
5. Updates file_source_meta.ai_metadata
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.ai_asset_metadata import AIAssetKPISuggestion, AIAssetTagSuggestion
from app.models.file_source_meta import FileSourceMeta
from app.services.reference_catalog_service import get_tags_and_kpis_for_ai_prompt

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(120.0, connect=10.0)

CATALOG_PROFILE_PROMPT = """You are analyzing a data file uploaded into Tablescope, a business analytics platform with a governed metadata catalog.

## File Information
File name: {file_name}
View name: {view_name}
Row count: {row_count}
Column count: {column_count}

## Columns
{columns_text}

## Sample Rows (first {sample_count})
{sample_rows}

## Reference Tags (governed catalog)
{reference_tags}

## Reference KPIs (governed catalog)
{reference_kpis}

## Instructions
Classify this file against the provided reference catalog. Return STRICT JSON with these keys:

1. "summary" — What is this file? (1-2 sentences)
2. "business_domain" — The most relevant business domain from the catalog (e.g. "sales_operations", "supply_chain")
3. "process_area" — The most relevant process area (e.g. "order_management", "logistics")
4. "suggested_tags" — Array of tags from the reference catalog that match this file:
   [{{"tag_key": "...", "display_name": "...", "confidence": 0.0-1.0, "reason": "brief explanation"}}]
   IMPORTANT: Use ONLY tag_key values from the reference tags list above. Do not invent new tags unless absolutely no catalog tag fits.
   If you must suggest a new tag, mark it as: {{"tag_key": "custom_...", "display_name": "...", "confidence": ..., "reason": "...", "is_custom": true}}
   Suggest 2-8 tags.
5. "suggested_kpis" — Array of KPIs from the reference catalog that this file can support:
   [{{"kpi_key": "...", "display_name": "...", "confidence": 0.0-1.0, "field_mapping": {{"required_field_name": "actual_column_name"}}, "reason": "brief explanation"}}]
   IMPORTANT: Only suggest KPIs whose required_fields are present (or can be confidently mapped) in the file columns.
   Suggest 1-6 KPIs.
6. "relationship_hints" — Array of likely foreign key relationships:
   [{{"source_field": "ColumnName", "possible_target": "TableName.ColumnName", "confidence": 0.0-1.0}}]
7. "data_quality_notes" — Array of data quality observations:
   ["note 1", "note 2"]

Return ONLY valid JSON. No markdown, no explanation outside JSON.
"""


async def profile_uploaded_file(
    session: AsyncSession,
    tenant_id: int,
    user_id: int,
    project_id: int,
    source_id: int,
    view_name: str,
    file_name: str,
    columns: list[dict[str, Any]],
    sample_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify an uploaded file against the reference catalog and persist suggestions."""
    settings = get_settings()

    catalog_data = await get_tags_and_kpis_for_ai_prompt(session, tenant_id)

    ref_tags_text = json.dumps(catalog_data["reference_tags"], indent=2)
    ref_kpis_text = json.dumps(catalog_data["reference_kpis"], indent=2)

    columns_text = "\n".join(
        f"- {c.get('name', '?')}: type={c.get('type', '?')}"
        for c in columns
    )
    sample_text = "\n".join(
        f"Row {i+1}: {json.dumps({k: str(v)[:50] for k, v in row.items()})}"
        for i, row in enumerate(sample_rows[:10])
    ) or "(no sample rows)"

    prompt = CATALOG_PROFILE_PROMPT.format(
        file_name=file_name,
        view_name=view_name,
        row_count=len(sample_rows),
        column_count=len(columns),
        columns_text=columns_text,
        sample_count=min(len(sample_rows), 10),
        sample_rows=sample_text,
        reference_tags=ref_tags_text,
        reference_kpis=ref_kpis_text,
    )

    ai_result = await _call_ai(settings, prompt, tenant_id, user_id, project_id)

    if ai_result:
        await _persist_suggestions(
            session, tenant_id, project_id, user_id, source_id, ai_result
        )
        await _update_file_meta(session, source_id, ai_result)

    return ai_result or _empty_result()


async def _call_ai(
    settings: Any,
    prompt: str,
    tenant_id: int,
    user_id: int,
    project_id: int,
) -> dict[str, Any] | None:
    """Call the AI server with the catalog-enriched prompt."""
    if not settings.tablescope_ai_enabled or not settings.tablescope_ai_api_url:
        logger.info("AI not configured")
        return None

    def _sign(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hmac.new(
            settings.tablescope_ai_signing_secret.encode(),
            canonical.encode(),
            hashlib.sha256,
        ).hexdigest()

    try:
        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "question": prompt,
            "scope": "project",
            "include_query_history": False,
            "include_dashboard_context": False,
            "timestamp": time.time(),
        }
        payload["signature"] = _sign(payload)

        url = f"{settings.tablescope_ai_api_url}/ai/ask"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            result = resp.json()

        answer = result.get("answer", "")
        parsed = _extract_json(answer)
        if parsed:
            return _validate_catalog_result(parsed)

        logger.warning("Could not parse JSON from AI catalog profile response")
        return None

    except Exception as e:
        logger.warning("AI catalog profiling failed: %s", e)
        return None


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract JSON object from text that might have markdown fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        start = 1
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip() == "```":
                end = i
                break
        cleaned = "\n".join(lines[start:end])

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    brace_start = cleaned.find("{")
    if brace_start >= 0:
        depth = 0
        for i in range(brace_start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[brace_start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


def _validate_catalog_result(result: dict[str, Any]) -> dict[str, Any]:
    """Ensure AI result has all expected keys with valid structure."""
    return {
        "summary": result.get("summary", ""),
        "business_domain": result.get("business_domain", ""),
        "process_area": result.get("process_area", ""),
        "suggested_tags": [
            {
                "tag_key": t.get("tag_key", ""),
                "display_name": t.get("display_name", t.get("tag_key", "")),
                "confidence": min(max(float(t.get("confidence", 0.5)), 0), 1),
                "reason": t.get("reason", ""),
                "is_custom": t.get("is_custom", False),
            }
            for t in result.get("suggested_tags", [])
            if isinstance(t, dict) and t.get("tag_key")
        ],
        "suggested_kpis": [
            {
                "kpi_key": k.get("kpi_key", ""),
                "display_name": k.get("display_name", k.get("kpi_key", "")),
                "confidence": min(max(float(k.get("confidence", 0.5)), 0), 1),
                "field_mapping": k.get("field_mapping", {}),
                "reason": k.get("reason", ""),
            }
            for k in result.get("suggested_kpis", [])
            if isinstance(k, dict) and k.get("kpi_key")
        ],
        "relationship_hints": result.get("relationship_hints", []),
        "data_quality_notes": result.get("data_quality_notes", []),
    }


async def _persist_suggestions(
    session: AsyncSession,
    tenant_id: int,
    project_id: int,
    user_id: int,
    source_id: int,
    result: dict[str, Any],
) -> None:
    """Write AI suggestions to the database."""
    for tag in result.get("suggested_tags", []):
        suggestion = AIAssetTagSuggestion(
            tenant_id=tenant_id,
            project_id=project_id,
            source_type="file_datasource",
            source_id=source_id,
            tag_key=tag["tag_key"],
            display_name=tag["display_name"],
            confidence=tag.get("confidence"),
            reason=tag.get("reason"),
            status="suggested",
            created_by=user_id,
        )
        session.add(suggestion)

    for kpi in result.get("suggested_kpis", []):
        suggestion = AIAssetKPISuggestion(
            tenant_id=tenant_id,
            project_id=project_id,
            source_type="file_datasource",
            source_id=source_id,
            kpi_key=kpi["kpi_key"],
            display_name=kpi["display_name"],
            confidence=kpi.get("confidence"),
            field_mapping=kpi.get("field_mapping", {}),
            reason=kpi.get("reason"),
            status="suggested",
            created_by=user_id,
        )
        session.add(suggestion)

    await session.flush()


async def _update_file_meta(
    session: AsyncSession,
    source_id: int,
    result: dict[str, Any],
) -> None:
    """Update file_source_meta with the AI metadata."""
    from datetime import datetime, timezone

    ai_metadata = {
        "summary": result.get("summary", ""),
        "business_domain": result.get("business_domain", ""),
        "process_area": result.get("process_area", ""),
        "suggested_tags": result.get("suggested_tags", []),
        "suggested_kpis": result.get("suggested_kpis", []),
        "relationship_hints": result.get("relationship_hints", []),
        "data_quality_notes": result.get("data_quality_notes", []),
    }

    await session.execute(
        update(FileSourceMeta)
        .where(FileSourceMeta.id == source_id)
        .values(
            ai_metadata=ai_metadata,
            ai_profile_status="profiled",
            ai_profiled_at=datetime.now(timezone.utc),
        )
    )
    await session.flush()


def _empty_result() -> dict[str, Any]:
    return {
        "summary": "",
        "business_domain": "",
        "process_area": "",
        "suggested_tags": [],
        "suggested_kpis": [],
        "relationship_hints": [],
        "data_quality_notes": [],
    }
