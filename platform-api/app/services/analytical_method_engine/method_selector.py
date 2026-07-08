"""Stage B — Method Selector.

Maps ``(analysisIntent x data profile) -> method`` using the runtime selection
matrix and profile-aware overrides. **Never calls the LLM.** Returns the chosen
method id, the ordered reasons, the alternatives considered, and the resolved
column roles — or a ``no_method`` outcome the executor turns into a safe result.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.analytical_method_engine import method_registry
from app.services.analytical_method_engine.column_roles import resolve_roles


class Selection:
    def __init__(
        self,
        *,
        method_id: str | None,
        roles: dict[str, Any] | None,
        reasons: list[str],
        alternatives: list[str],
        rejected: dict[str, str],
        status: str,
    ) -> None:
        self.method_id = method_id
        self.roles = roles or {}
        self.reasons = reasons
        self.alternatives = alternatives
        self.rejected = rejected
        self.status = status  # "selected" | "no_method" | "no_registry"


def _prefer_robust(intent: str, profile: dict[str, Any], roles: dict[str, Any]) -> bool:
    """True when the data favors a rank/robust method over a parametric one.

    For relationship intents we key off *outliers* only — marginal non-normality
    of a predictor (e.g. a uniform time index) does not violate Pearson. For
    group comparisons, non-normality of the measured value also matters.
    """
    check_normality = intent in ("compare_two_groups", "compare_multiple_groups",
                                 "compare_paired", "compare_to_target")
    cols = [roles.get("x"), roles.get("y"), roles.get("value")]
    for c in cols:
        if not c:
            continue
        info = profile["columns"].get(c, {})
        if (info.get("outlier_rate") or 0) > 0.05:
            return True
        if check_normality and info.get("is_normal") is False:
            return True
    return False


def _overdispersed(profile: dict[str, Any], roles: dict[str, Any]) -> bool:
    target = roles.get("target")
    if not target:
        return False
    info = profile["columns"].get(target, {})
    mean = info.get("mean")
    std = info.get("std")
    if mean and std and mean > 0:
        return (std * std) > (1.5 * mean)  # variance >> mean
    return False


async def select_method(
    session: AsyncSession, intent: str, profile: dict[str, Any]
) -> Selection:
    registry = await method_registry.get_active_registry(session)
    if registry is None:
        return Selection(
            method_id=None, roles=None, reasons=[], alternatives=[],
            rejected={}, status="no_registry",
        )

    roles = resolve_roles(intent, profile)
    if roles is None:
        return Selection(
            method_id=None, roles=None,
            reasons=[f"Data shape does not support intent '{intent}'"],
            alternatives=[], rejected={}, status="no_method",
        )

    rows = await method_registry.resolve_selection_matrix(session, intent)
    if not rows:
        return Selection(
            method_id=None, roles=roles,
            reasons=[f"No selection matrix row for intent '{intent}'"],
            alternatives=[], rejected={}, status="no_method",
        )

    row = rows[0]
    candidates = [row["primary_method_id"], *row.get("alternative_method_ids", [])]

    reasons: list[str] = []
    # Profile-aware ordering: promote a robust/nonparametric alternative first.
    if intent in ("relationship_numeric", "compare_two_groups", "compare_multiple_groups",
                  "compare_paired", "compare_to_target") and _prefer_robust(intent, profile, roles):
        reasons.append("Data is non-normal or outlier-prone; preferring a robust/rank method")
        robust = [c for c in candidates if c != row["primary_method_id"]]
        candidates = [*robust, row["primary_method_id"]]
    if intent in ("count_outcome", "zero_heavy_count") and _overdispersed(profile, roles):
        reasons.append("Count outcome is overdispersed; preferring negative-binomial")
        candidates = [
            "negative_binomial_regression",
            *[c for c in candidates if c != "negative_binomial_regression"],
        ]

    rejected: dict[str, str] = {}
    chosen: str | None = None
    for cand in candidates:
        method = registry["methods"].get(cand)
        if method is None:
            rejected[cand] = "not active/executable in registry"
            continue
        chosen = cand
        break

    if chosen is None:
        return Selection(
            method_id=None, roles=roles,
            reasons=[*reasons, "No executable method available for this intent"],
            alternatives=candidates, rejected=rejected, status="no_method",
        )

    method = registry["methods"][chosen]
    reasons = reasons + list(method.get("selection_rules") or [])
    alternatives = [c for c in candidates if c != chosen]
    return Selection(
        method_id=chosen, roles=roles, reasons=reasons,
        alternatives=alternatives, rejected=rejected, status="selected",
    )
