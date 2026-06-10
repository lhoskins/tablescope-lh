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
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.ai_asset_metadata import AIAssetKPISuggestion, AIAssetTagSuggestion
from app.models.file_source_meta import FileSourceMeta
from app.services.reference_catalog_service import get_tags_and_kpis_for_ai_prompt

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(120.0, connect=10.0)

CATALOG_PROFILE_PROMPT = """You are a data classification expert analyzing ONE specific uploaded file.

## THIS FILE
File name: {file_name}
View name: {view_name}
Rows: {row_count} | Columns: {column_count}

## THIS FILE'S COLUMNS (analyze these carefully)
{columns_text}

## THIS FILE'S SAMPLE DATA (first {sample_count} rows)
{sample_rows}

## Available Reference Tags
{reference_tags}

## Available Reference KPIs
{reference_kpis}

## CRITICAL RULES
1. You MUST analyze THIS specific file's columns and sample data. Do NOT give generic answers.
2. Each tag you suggest must be justified by actual column names or data values in THIS file.
3. Each KPI you suggest must have its required_fields mappable to actual columns in THIS file.
4. Compare each reference tag's "example_fields" against THIS file's actual columns. Only suggest tags where there is a clear match.
5. Compare each reference KPI's "required_fields" against THIS file's actual columns. Only suggest KPIs where the required columns exist.
6. Do NOT suggest tags/KPIs about infrastructure monitoring (uptime, downtime, MTBF) for a file about patch compliance or change management. The file's ACTUAL columns determine what tags/KPIs apply.

## COLUMN MATCHING EXAMPLES
- File has "AssetID", "PatchStatus", "OperatingSystem" → suggests "asset_inventory", "patch_management"
- File has "ChangeID", "Outcome", "RiskLevel" → suggests "change_management"
- File has "CostUSD", "Provider", "Service" → suggests "cloud_cost"
- File has "IncidentID", "Priority", "ResolvedDate" → suggests "incident_management"

## Return STRICT JSON:
{{
  "summary": "1-2 sentences describing what THIS specific file contains based on its columns and data",
  "business_domain": "domain from catalog matching THIS file's content",
  "process_area": "process area matching THIS file's content",
  "suggested_tags": [
    {{"tag_key": "from_catalog", "display_name": "...", "confidence": 0.0-1.0, "reason": "THIS file has columns X, Y that match this tag"}}
  ],
  "suggested_kpis": [
    {{"kpi_key": "from_catalog", "display_name": "...", "confidence": 0.0-1.0, "field_mapping": {{"required_field": "actual_column_in_this_file"}}, "reason": "THIS file has column X that maps to required_field Y"}}
  ],
  "relationship_hints": [
    {{"source_field": "ActualColumnInThisFile", "possible_target": "OtherTable.Column", "confidence": 0.0-1.0}}
  ],
  "data_quality_notes": ["observations about THIS file's data"]
}}

IMPORTANT: Only use tag_key/kpi_key values from the reference lists above. If no catalog tag fits, create: {{"tag_key": "custom_...", "display_name": "...", "is_custom": true}}.
Suggest 3-8 tags and 2-6 KPIs that are SPECIFIC to THIS file.

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
    persist: bool = True,
) -> dict[str, Any]:
    """Classify an uploaded file against the reference catalog and optionally persist suggestions."""
    settings = get_settings()

    catalog_data = await get_tags_and_kpis_for_ai_prompt(session, tenant_id)

    col_names_lower = {c.get("name", "").lower().replace("_", "") for c in columns}

    def _col_overlap(example_fields: list[str]) -> bool:
        for ef in example_fields:
            if ef.lower().replace("_", "") in col_names_lower:
                return True
        return False

    relevant_tags = [
        t for t in catalog_data["reference_tags"]
        if _col_overlap(t.get("example_fields", []))
    ]
    relevant_kpis = [
        k for k in catalog_data["reference_kpis"]
        if _col_overlap(k.get("required_fields", []))
    ]

    if not relevant_tags:
        relevant_tags = catalog_data["reference_tags"]
    if not relevant_kpis:
        relevant_kpis = catalog_data["reference_kpis"]

    ref_tags_text = json.dumps(relevant_tags, indent=2)
    ref_kpis_text = json.dumps(relevant_kpis, indent=2)

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

    logger.info(
        "Catalog profiling %s: %d columns [%s], %d relevant tags, %d relevant KPIs",
        file_name,
        len(columns),
        ", ".join(c.get("name", "?") for c in columns),
        len(relevant_tags),
        len(relevant_kpis),
    )

    ai_result = await _call_ai(settings, prompt, tenant_id, user_id, project_id)
    if ai_result:
        logger.info(
            "Catalog profile result for %s: domain=%s, tags=%s, kpis=%s",
            file_name,
            ai_result.get("business_domain"),
            [t.get("tag_key") for t in ai_result.get("suggested_tags", [])],
            [k.get("kpi_key") for k in ai_result.get("suggested_kpis", [])],
        )

    if ai_result and persist and source_id and project_id:
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
        kpi_suggestion = AIAssetKPISuggestion(
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
        session.add(kpi_suggestion)

    await session.flush()


async def _update_file_meta(
    session: AsyncSession,
    source_id: int,
    result: dict[str, Any],
) -> None:
    """Update file_source_meta with the AI metadata."""
    from datetime import UTC, datetime

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
            ai_profiled_at=datetime.now(UTC),
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
