"""AI file analysis service — sends compact file profile to LLM for analysis.

Returns structured summary, tags, field descriptions, and recommendations.
Uses the same AI proxy infrastructure as the rest of the platform.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(120.0, connect=10.0)

FILE_ANALYSIS_PROMPT = """You are analyzing a data file uploaded into Tablescope, a business analytics platform.

Given the file metadata, field profiles, and sample rows below, produce a structured JSON analysis.

## File Information
File name: {file_name}
File type: {file_type}
Row count: {row_count}
Column count: {column_count}
{sheet_info}

## Field Profiles
{field_profiles}

## Sample Rows (first {sample_count})
{sample_rows}

## Instructions
Analyze this file and return STRICT JSON with these keys:

1. "summary" — What is this file? (1-2 sentences)
2. "usage_summary" — How will this file likely be used in analytics? (1-2 sentences)
3. "quality_summary" — What data quality issues or risks exist? (1-2 sentences, or "No issues detected.")
4. "tags" — Array of relevant tags:
   [{{"tag": "name", "tag_type": "domain|entity|metric|time|geography|quality|workflow", "confidence": 0.0-1.0}}]
   Generate 3-8 tags. tag_type values: domain (business area), entity (thing), metric (measure), time (date/time), geography (location), quality (data issue), workflow (process).
5. "fields" — Array of field analysis (one per field):
   [{{"field_name": "...", "description": "...", "recommended_type": "string|integer|decimal|date|boolean", "quality_notes": "..."}}]
6. "recommendations" — Array of actionable suggestions:
   [{{"recommendation_type": "rename_field|change_field_type|flag_nulls|flag_duplicates|suggest_primary_key|suggest_date_field|suggest_metric|suggest_dimension|standardize_values|ignore_field", "title": "...", "description": "...", "severity": "info|warning|critical", "suggested_action": {{"field": "...", "action": "..."}}}}]
   Generate 2-6 recommendations.

Return ONLY valid JSON. No markdown, no explanation outside JSON.
"""


async def analyze_file_with_ai(
    profile: dict[str, Any],
    project_context: dict[str, Any] | None = None,
    tenant_id: int = 0,
    user_id: int = 0,
    project_id: int = 0,
) -> dict[str, Any]:
    """Send compact file profile to AI and return structured analysis.

    Uses ONLY the dedicated /ai/analyze-file endpoint. If it is unavailable,
    degrades to a deterministic system-only profile (no /ai/ask fallback).
    """
    import hashlib
    import hmac
    import time

    settings = get_settings()
    if not settings.tablescope_ai_enabled or not settings.tablescope_ai_api_url:
        logger.info("AI not configured — returning system-only profile")
        return _fallback_analysis(profile)

    field_profiles_text = _format_field_profiles(profile.get("fields", []))
    sample_rows_text = _format_sample_rows(profile.get("sample_rows", []))
    sheet_info = f"Sheet: {profile.get('sheet_name')}" if profile.get("sheet_name") else ""

    prompt = FILE_ANALYSIS_PROMPT.format(
        file_name=profile.get("file_name", "unknown"),
        file_type=profile.get("file_type", "unknown"),
        row_count=profile.get("row_count", 0),
        column_count=profile.get("column_count", 0),
        sheet_info=sheet_info,
        field_profiles=field_profiles_text,
        sample_count=min(len(profile.get("sample_rows", [])), 10),
        sample_rows=sample_rows_text,
    )

    def _sign(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hmac.new(
            settings.tablescope_ai_signing_secret.encode(),
            canonical.encode(),
            hashlib.sha256,
        ).hexdigest()

    # Try dedicated analyze-file endpoint first
    try:
        payload: dict[str, Any] = {
            "prompt": prompt,
            "task": "file_analysis",
            "response_format": "json",
            "timestamp": time.time(),
        }
        payload["signature"] = _sign(payload)

        url = f"{settings.tablescope_ai_api_url}/ai/analyze-file"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            result = resp.json()

        if "analysis" in result:
            return _validate_ai_result(result["analysis"], profile)
        return _validate_ai_result(result, profile)

    except Exception as e:
        # No /ai/ask fallback: file analysis uses ONLY the dedicated
        # /ai/analyze-file endpoint. The generic Q&A endpoint is SQL-oriented
        # and produces unusable output for extraction. If the dedicated
        # endpoint fails, degrade to a deterministic system-only profile.
        logger.warning(
            "analyze-file endpoint failed (%s) — returning system-only profile", e,
        )
        return _fallback_analysis(profile)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract a JSON object from text that might have markdown fences."""
    cleaned = text.strip()
    # Strip markdown code fences
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first line (```json) and last line (```)
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

    # Try to find JSON object in the text
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


def _format_field_profiles(fields: list[dict[str, Any]]) -> str:
    lines = []
    for f in fields:
        line = (
            f"- {f['field_name']}: type={f.get('detected_type', '?')}, "
            f"nulls={f.get('null_count', 0)} ({f.get('null_percent', 0):.1f}%), "
            f"distinct={f.get('distinct_count', 0)}, "
            f"length={f.get('min_length', 0)}-{f.get('max_length', 0)}, "
            f"samples={f.get('sample_values', [])[:3]}"
        )
        lines.append(line)
    return "\n".join(lines) or "(no fields)"


def _format_sample_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "(no sample rows)"
    lines = []
    for i, row in enumerate(rows[:10]):
        truncated = {k: str(v)[:50] for k, v in row.items()}
        lines.append(f"Row {i + 1}: {json.dumps(truncated)}")
    return "\n".join(lines)


def _validate_ai_result(
    result: dict[str, Any], profile: dict[str, Any]
) -> dict[str, Any]:
    """Ensure the AI result has all required keys with sensible defaults."""
    validated: dict[str, Any] = {
        "summary": result.get("summary", "File uploaded successfully."),
        "usage_summary": result.get("usage_summary", "Available for queries and dashboards."),
        "quality_summary": result.get("quality_summary", "No issues detected."),
        "tags": [],
        "fields": [],
        "recommendations": [],
    }

    for tag in result.get("tags", []):
        if isinstance(tag, dict) and "tag" in tag:
            validated["tags"].append({
                "tag": str(tag["tag"])[:100],
                "tag_type": str(tag.get("tag_type", "user"))[:50],
                "confidence": min(max(float(tag.get("confidence", 0.5)), 0), 1),
            })

    field_names = {f["field_name"] for f in profile.get("fields", [])}
    for field in result.get("fields", []):
        if isinstance(field, dict) and field.get("field_name") in field_names:
            validated["fields"].append({
                "field_name": field["field_name"],
                "description": str(field.get("description", ""))[:500],
                "recommended_type": str(field.get("recommended_type", "string"))[:100],
                "quality_notes": str(field.get("quality_notes", ""))[:500],
            })

    for rec in result.get("recommendations", []):
        if isinstance(rec, dict) and "title" in rec:
            validated["recommendations"].append({
                "recommendation_type": str(rec.get("recommendation_type", "info"))[:100],
                "title": str(rec["title"])[:255],
                "description": str(rec.get("description", ""))[:1000],
                "severity": str(rec.get("severity", "info"))[:50],
                "suggested_action": rec.get("suggested_action"),
            })

    return validated


def _fallback_analysis(profile: dict[str, Any]) -> dict[str, Any]:
    """Generate a basic analysis without AI — purely from profiling stats."""
    fields_data = profile.get("fields", [])
    file_name = profile.get("file_name", "unknown")
    row_count = profile.get("row_count", 0)
    col_count = profile.get("column_count", 0)

    null_fields = [f["field_name"] for f in fields_data if f.get("null_count", 0) > 0]
    quality_notes = (
        f"Fields with null values: {', '.join(null_fields[:5])}"
        if null_fields else "No null values detected."
    )

    tags = []
    name_lower = file_name.lower()
    for keyword, tag_type in [
        ("sales", "domain"), ("order", "entity"), ("customer", "entity"),
        ("product", "entity"), ("invoice", "domain"), ("revenue", "metric"),
        ("employee", "entity"), ("inventory", "domain"), ("transaction", "entity"),
    ]:
        if keyword in name_lower:
            tags.append({"tag": keyword, "tag_type": tag_type, "confidence": 0.7})

    fields = []
    for f in fields_data:
        fields.append({
            "field_name": f["field_name"],
            "description": "",
            "recommended_type": f.get("detected_type", "string"),
            "quality_notes": f"Nulls: {f.get('null_count', 0)}" if f.get("null_count", 0) > 0 else "",
        })

    recommendations = []
    for f in fields_data:
        if f.get("distinct_count", 0) == row_count and row_count > 0:
            recommendations.append({
                "recommendation_type": "suggest_primary_key",
                "title": f"Consider {f['field_name']} as primary key",
                "description": f"{f['field_name']} has {f['distinct_count']} distinct values across {row_count} rows (100% unique).",
                "severity": "info",
                "suggested_action": {"field": f["field_name"], "action": "mark_identifier"},
            })
        if f.get("detected_type") == "date":
            recommendations.append({
                "recommendation_type": "suggest_date_field",
                "title": f"Use {f['field_name']} as time dimension",
                "description": f"{f['field_name']} appears to contain date values.",
                "severity": "info",
                "suggested_action": {"field": f["field_name"], "action": "mark_date"},
            })

    return {
        "summary": f"File '{file_name}' contains {row_count} rows and {col_count} columns.",
        "usage_summary": "Available for queries and dashboards.",
        "quality_summary": quality_notes,
        "tags": tags,
        "fields": fields,
        "recommendations": recommendations[:6],
    }
