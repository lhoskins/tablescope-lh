"""Stage D — Result Envelope.

Assembles the standardized, auditable envelope returned for every analytical
run: the method chosen and why, the data profile summary, assumption validation,
the statistical results, caveats, quality, and governance/audit metadata. The
LLM receives this envelope (plus the method card) and nothing else.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

ENGINE_VERSION = "1.0.0"


def _parameter_hash(intent: str, roles: dict[str, Any], method_id: str | None) -> str:
    payload = json.dumps(
        {"intent": intent, "roles": roles, "method": method_id}, sort_keys=True, default=str
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "rowCount": profile.get("row_count"),
        "numericColumns": profile.get("numeric_columns"),
        "categoricalColumns": profile.get("categorical_columns"),
        "datetimeColumns": profile.get("datetime_columns"),
        "collinearityMax": profile.get("collinearity_max"),
        "hasTimeStructure": profile.get("has_time_structure"),
    }


def build(
    *,
    intent: str,
    profile: dict[str, Any],
    method: dict[str, Any] | None,
    roles: dict[str, Any] | None = None,
    selection_reasons: list[str],
    alternatives: list[str],
    exec_result: dict[str, Any],
    registry_version: int | None,
) -> dict[str, Any]:
    method_id = method.get("method_id") if method else None
    roles = roles or {}
    envelope: dict[str, Any] = {
        "status": exec_result.get("status", "error"),
        "analysisIntent": intent,
        "method": method_id,
        "methodName": method.get("display_name") if method else None,
        "tier": method.get("tier") if method else None,
        "selectedMethodReason": selection_reasons,
        "alternativesConsidered": alternatives,
        "dataProfile": _profile_summary(profile),
        "n": exec_result.get("n"),
        "usableN": exec_result.get("usable_n"),
        "excludedOutliers": exec_result.get("excluded"),
        "missing": exec_result.get("missing"),
        "results": exec_result.get("results", {}),
        "assumptions": exec_result.get("assumptions", []),
        "caveats": exec_result.get("caveats", []),
        "quality": exec_result.get("quality"),
        "warnings": exec_result.get("warnings", []),
        "reason": exec_result.get("reason"),
        "executionEngine": exec_result.get("executionEngine")
        or (method.get("execution_engine") if method else None),
        "fallbackFrom": exec_result.get("fallbackFrom"),
        "resultSchemaVersion": method.get("result_schema_version") if method else None,
        "chartContract": method.get("chart_contract") if method else None,
        "methodCard": method.get("method_card") if method else None,
        "outputContract": method.get("output_contract") if method else None,
        "audit": {
            "engineVersion": ENGINE_VERSION,
            "methodRegistryVersion": registry_version,
            "catalogMethodId": method_id,
            "inputDataHash": profile.get("hash"),
            "parameterHash": _parameter_hash(intent, roles, method_id),
        },
    }
    return envelope
