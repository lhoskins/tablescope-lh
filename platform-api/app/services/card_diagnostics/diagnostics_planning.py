
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: Diagnostic stages, in the order an analyst would work a finding.
#: Testing what the card's own narrative asserts. Leads the ladder: a
#: contradicted claim invalidates the story the rest of the steps sit inside.
STAGE_VERIFY = "verify"
STAGE_LOCALISE = "localise"
STAGE_WHEN = "when"
STAGE_QUANTIFY = "quantify"
STAGE_EXPLAIN = "explain"
STAGE_PROJECT = "project"
STAGE_CORROBORATE = "corroborate"

#: Card families this module dissects.
RISK = "risk"
TREND = "trend"
OPPORTUNITY = "opportunity"

_CHANGE_WORDS = re.compile(
    r"(?i)\b(increase|increased|increasing|decrease|decreased|decreasing|rose|"
    r"rising|fell|falling|drop|dropped|decline|declining|growth|grew|shrank|"
    r"spike|surge|slump|change|changed|shift|shifted|worse|worsening|improve|"
    r"improved|improving|up|down|versus|vs)\b"
)
_THRESHOLD_WORDS = re.compile(
    r"(?i)\b(breach|breached|exceed|exceeded|exceeding|above|below|over|under|"
    r"miss|missed|missing|target|sla|limit|threshold|out of spec|non-?compliant)\b"
)


def card_family(card: dict[str, Any]) -> str | None:
    """Classify a card as risk / trend / opportunity, or ``None``."""
    itype = str(card.get("insightType") or card.get("insight_type") or "").lower()
    severity = str(card.get("severity") or "").lower()
    if itype.startswith("risk") or severity in {"critical", "urgent", "warning"}:
        return RISK
    if itype.startswith("opportunity") or severity == "opportunity":
        return OPPORTUNITY
    if itype.startswith(("trend", "relationship")):
        return TREND
    return None


@dataclass(frozen=True)
class DiagnosticSpec:
    """One diagnostic step against a specific card."""

    stage: str
    intent: str
    title: str
    question: str
    #: Why this step is being run — shown to the user so the card reads as a
    #: line of reasoning rather than a pile of charts.
    rationale: str
    priority: float = 0.5
    group_by: str | None = None
    #: True when the step was added because a trigger fired (see
    #: :func:`period_comparison_triggers`), rather than being part of the
    #: standard ladder.
    triggered_by: str | None = None


@dataclass
class ActionProposal:
    """A proposed next step derived from what the diagnostics found."""

    headline: str
    rationale: str
    kind: str  # "mitigate" | "capture" | "investigate" | "monitor"
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "rationale": self.rationale,
            "kind": self.kind,
            "confidence": self.confidence,
        }


# ── When is a period comparison actually warranted? ──────────────────────────


def period_comparison_triggers(
    card: dict[str, Any], findings: dict[str, Any] | None = None
) -> list[str]:
    """Reasons a MoM/YoY comparison is justified for this card, if any.

    A period comparison is computable from nearly any dated measure, so running
    it unconditionally floods the section with interchangeable cards. It earns
    its place only when something points at a change worth sizing.
    """
    reasons: list[str] = []
    text = " ".join(
        str(card.get(k) or "") for k in ("title", "summary", "recommendedAction")
    )
    if _CHANGE_WORDS.search(text):
        reasons.append("the finding describes a change")
    if _THRESHOLD_WORDS.search(text):
        reasons.append("a target or threshold is involved")
    if card_family(card) == TREND:
        reasons.append("the card is a trend")

    facts = findings or {}
    if facts.get("change_point_count"):
        reasons.append("a level shift was detected")
    if facts.get("anomaly_count"):
        reasons.append("anomalous observations were detected")
    if facts.get("threshold_breached"):
        reasons.append("a threshold breach was measured")
    return reasons


def should_compare_periods(
    card: dict[str, Any], findings: dict[str, Any] | None = None
) -> bool:
    """True when a period comparison supports this card's finding."""
    return bool(period_comparison_triggers(card, findings))


# ── The diagnostic ladder ────────────────────────────────────────────────────


def plan_card_diagnostics(
    card: dict[str, Any],
    *,
    metric: str | None = None,
    dimensions: list[str] | None = None,
    period_column: str | None = None,
    period_count: int = 0,
    row_count: int = 0,
    related_measures: list[str] | None = None,
    findings: dict[str, Any] | None = None,
    max_steps: int = 5,
) -> list[DiagnosticSpec]:
    """Plan the diagnostics that dissect one card's finding.

    ``dimensions`` must already exclude identifier and period columns. The plan
    is ordered so the most actionable question — *where is this concentrated?* —
    comes first, and a period comparison appears only when triggered.
    """
    family = card_family(card)
    if family is None:
        return []

    subject = metric or _infer_metric(card) or "this metric"
    dims = dimensions or []
    specs: list[DiagnosticSpec] = []

    # 1. Localise: the single most actionable question about any finding.
    if dims:
        dim = dims[0]
        specs.append(
            DiagnosticSpec(
                stage=STAGE_LOCALISE,
                intent="compare_multiple_groups",
                title=f"Where {subject} is concentrated",
                question=f"Which {_humanize(dim)} accounts for the {subject} finding?",
                rationale=(
                    "Pinpoints the segment carrying the problem so action can be "
                    "targeted instead of applied across the board."
                ),
                priority=0.98,
                group_by=dim,
            )
        )
        if period_column:
            specs.append(
                DiagnosticSpec(
                    stage=STAGE_LOCALISE,
                    intent="contribution_to_change",
                    title=f"What drove the change in {subject}",
                    question=f"Which {_humanize(dim)} groups explain the movement in {subject}?",
                    rationale=(
                        "Separates the groups that moved the aggregate from those "
                        "that merely came along with it."
                    ),
                    priority=0.95,
                    group_by=dim,
                )
            )

    # 2. When did it start? A dated cause is a findable cause.
    if period_column and period_count >= 12:
        specs.append(
            DiagnosticSpec(
                stage=STAGE_WHEN,
                intent="detect_change_point",
                title=f"When {subject} shifted",
                question=f"Did {subject} move to a new level, and when?",
                rationale=(
                    "Dates the shift so it can be matched against a process, "
                    "supplier or policy change."
                ),
                priority=0.92,
            )
        )
        specs.append(
            DiagnosticSpec(
                stage=STAGE_QUANTIFY,
                intent="detect_anomalies",
                title=f"Unusual {subject} observations",
                question=f"Which {subject} observations fall outside the expected range?",
                rationale=(
                    "Distinguishes a genuine outlier worth investigating from "
                    "ordinary variation."
                ),
                priority=0.88,
            )
        )

    # 3. Explain: what co-moves, and what accounts for it.
    others = [m for m in (related_measures or []) if m != subject]
    if others and row_count >= 20:
        specs.append(
            DiagnosticSpec(
                stage=STAGE_EXPLAIN,
                intent="relationship_numeric",
                title=f"{subject} and {_humanize(others[0])}",
                question=f"Does {subject} move with {_humanize(others[0])}?",
                rationale=(
                    "Tests a candidate driver, so the proposed action targets a "
                    "cause rather than a symptom."
                ),
                priority=0.85,
            )
        )
    if len(others) >= 2 and row_count >= 20:
        specs.append(
            DiagnosticSpec(
                stage=STAGE_EXPLAIN,
                intent="continuous_prediction",
                title=f"What explains {subject}",
                question=f"Which measures account for movement in {subject}?",
                rationale="Ranks candidate drivers by how much variation each explains.",
                priority=0.8,
            )
        )

    # 4. Project: the cost of doing nothing.
    if period_column and period_count >= 12:
        specs.append(
            DiagnosticSpec(
                stage=STAGE_PROJECT,
                intent="forecast_time_series",
                title=f"Where {subject} is heading",
                question=f"What happens to {subject} if nothing changes?",
                rationale=(
                    "Sizes the cost of inaction, which is what justifies acting now."
                ),
                priority=0.75,
            )
        )

    # 5. Period comparison — TRIGGERED evidence, not a default.
    triggers = period_comparison_triggers(card, findings)
    if period_column and period_count >= 6 and triggers:
        specs.append(
            DiagnosticSpec(
                stage=STAGE_QUANTIFY,
                intent="compare_periods",
                title=f"{subject}: size of the change",
                question=f"How large is the change in {subject} versus the prior period?",
                rationale=f"Included because {triggers[0]}.",
                priority=0.7,
                triggered_by=triggers[0],
            )
        )

    specs.sort(key=lambda s: s.priority, reverse=True)
    return specs[:max_steps]


def _infer_metric(card: dict[str, Any]) -> str | None:
    """Best-effort subject metric for a card, from its explicit fields."""
    for key in ("metric", "metricLabel", "valueColumn"):
        value = card.get(key)
        if value:
            return str(value)
    chart = card.get("chart") or {}
    if isinstance(chart, dict):
        roles = chart.get("roles") or {}
        if isinstance(roles, dict) and roles.get("value"):
            return str(roles["value"])
    return None


def _humanize(column: str) -> str:
    cleaned = str(column or "").replace("_", " ").replace("-", " ").strip()
    return cleaned.title() if cleaned else str(column)
