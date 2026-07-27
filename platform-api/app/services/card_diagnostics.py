"""Purpose-driven Deeper analysis: dissect a finding, then propose what to do.

Deeper analysis used to scan *tables* and offer whatever generic analyses the
shape allowed. Because a period comparison can be computed from almost any
dated measure, month-over-month and year-over-year dominated every project — the
section answered "what can we compute?" instead of "what should we do about
this?".

This module inverts that. Deeper analysis takes an existing **Risk, Trend or
Opportunity card** and works it like an analyst would:

1. **Localise** — which segment carries the problem? (a plant, a supplier, a
   region — the answer you can act on)
2. **Time-localise** — when did it start? A level shift dates the cause.
3. **Quantify** — how abnormal is it, and how large?
4. **Explain** — what moves with it, and which measures account for it?
5. **Project** — where does it end up if nobody intervenes?
6. **Corroborate** — does another data source or document say the same thing?
7. **Act** — propose mitigation (risk) or capture (opportunity), tied to the
   evidence above.

**Period comparisons are demoted to triggered evidence.** MoM/YoY only earns a
place when something warrants it — the card is about a change, a threshold was
breached, an anomaly or level shift was detected — so it supports a finding
rather than being the finding.

Pure and dependency-light: planning, trigger logic, action proposals and
follow-up questions are all unit-testable without a database, an LLM or R.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, cast

logger = logging.getLogger(__name__)

#: Diagnostic stages, in the order an analyst would work a finding.
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


# ── Cross-referencing other sources and documents ────────────────────────────


@dataclass(frozen=True)
class CrossReference:
    """A corroborating source to check the finding against."""

    kind: str  # "table" | "document"
    name: str
    question: str
    rationale: str


def plan_cross_references(
    card: dict[str, Any],
    *,
    tables: list[str] | None = None,
    documents: list[dict[str, Any]] | None = None,
    max_refs: int = 4,
) -> list[CrossReference]:
    """Other sources worth checking the card's finding against.

    A finding measured in one table is a hypothesis until something else agrees.
    Documents matter as much as tables here: a board minute or monthly review
    often states the *reason* a metric moved, which no query can recover.
    """
    subject_terms = _subject_terms(card)
    own_tables = set()
    sources = card.get("sources") or {}
    if isinstance(sources, dict):
        own_tables = {str(t) for t in (sources.get("tables") or [])}

    refs: list[CrossReference] = []
    for table in tables or []:
        if str(table) in own_tables:
            continue  # already the card's own evidence
        if not subject_terms or _mentions(str(table), subject_terms):
            refs.append(
                CrossReference(
                    kind="table",
                    name=str(table),
                    question=f"Does {table!s} show the same pattern?",
                    rationale=(
                        "An independent table carrying the same measure either "
                        "corroborates the finding or narrows it to one source."
                    ),
                )
            )
        if len(refs) >= max_refs:
            return refs

    for doc in documents or []:
        title = str(doc.get("title") or doc.get("name") or "").strip()
        if not title:
            continue
        if not subject_terms or _mentions(title + " " + str(doc.get("summary") or ""), subject_terms):
            refs.append(
                CrossReference(
                    kind="document",
                    name=title,
                    question=f"Does {title} explain this finding?",
                    rationale=(
                        "Documents record decisions and causes — the explanation "
                        "behind a movement that the data alone cannot supply."
                    ),
                )
            )
        if len(refs) >= max_refs:
            break
    return refs[:max_refs]


def _subject_terms(card: dict[str, Any]) -> set[str]:
    text = " ".join(str(card.get(k) or "") for k in ("title", "summary", "metric"))
    words = re.findall(r"[a-z]{4,}", text.lower())
    stop = {"this", "that", "with", "from", "have", "than", "were", "where", "which", "insight"}
    return {w for w in words if w not in stop}


def _mentions(text: str, terms: set[str]) -> bool:
    lowered = str(text or "").lower()
    return any(t in lowered for t in terms)


# ── Proposing what to do ─────────────────────────────────────────────────────


def propose_actions(
    card: dict[str, Any], findings: dict[str, Any] | None = None, *, max_actions: int = 3
) -> list[ActionProposal]:
    """Turn diagnostics into proposed next steps.

    Proposals are grounded in what was actually measured — a concentrated
    segment, a dated shift, a projected trajectory. When nothing specific was
    found the proposal is to investigate or monitor, which is honest, rather
    than inventing a confident recommendation.
    """
    family = card_family(card)
    if family is None:
        return []
    facts = findings or {}
    subject = _infer_metric(card) or "this metric"
    proposals: list[ActionProposal] = []

    segment = facts.get("top_segment")
    if segment:
        share = facts.get("top_segment_share")
        share_text = f" (~{share:.0%} of the movement)" if isinstance(share, int | float) else ""
        proposals.append(
            ActionProposal(
                headline=(
                    f"Target {segment} first"
                    if family != OPPORTUNITY
                    else f"Scale what {segment} is doing"
                ),
                rationale=(
                    f"{segment} concentrates the {subject} finding{share_text}, so a "
                    "focused intervention there moves the aggregate fastest."
                ),
                kind="mitigate" if family != OPPORTUNITY else "capture",
                confidence="high",
            )
        )

    when = facts.get("change_point_period")
    if when:
        proposals.append(
            ActionProposal(
                headline=f"Review what changed around {when}",
                rationale=(
                    f"{subject} shifted to a new level at {when}; identifying the "
                    "process, supplier or policy change at that point isolates the cause."
                ),
                kind="investigate",
                confidence="high",
            )
        )

    driver = facts.get("top_driver")
    if driver:
        proposals.append(
            ActionProposal(
                headline=f"Address {_humanize(str(driver))}",
                rationale=(
                    f"{_humanize(str(driver))} accounts for a significant share of the "
                    f"variation in {subject}, making it the highest-leverage input to change."
                ),
                kind="mitigate" if family != OPPORTUNITY else "capture",
                confidence="medium",
            )
        )

    projected = facts.get("forecast_direction")
    if projected in {"worsening", "declining", "increasing"} and family == RISK:
        proposals.append(
            ActionProposal(
                headline="Act before the trajectory compounds",
                rationale=(
                    f"{subject} is projected to keep {projected} if nothing changes, so "
                    "the cost of delay grows each period."
                ),
                kind="mitigate",
                confidence="medium",
            )
        )

    if not proposals:
        proposals.append(
            ActionProposal(
                headline=(
                    "Investigate before acting" if family == RISK else "Monitor for confirmation"
                ),
                rationale=(
                    "The diagnostics did not isolate a segment, a dated shift or a "
                    "driver, so there is no evidence yet to justify a targeted action."
                ),
                kind="investigate" if family == RISK else "monitor",
                confidence="low",
            )
        )
    return proposals[:max_actions]


# ── Questions the user can ask about the card ────────────────────────────────


def suggested_followups(
    card: dict[str, Any], *, dimensions: list[str] | None = None, max_items: int = 5
) -> list[str]:
    """Concrete next questions for the card's ask box.

    Phrased as things a user would actually type, and scoped to this card so the
    conversation continues the finding instead of starting a new topic.
    """
    family = card_family(card)
    if family is None:
        return []
    subject = _infer_metric(card) or "this"
    dims = dimensions or []
    # Ordered by purpose, not by convenience: the question that leads to an
    # action comes before generic drill-downs, because a truncated list must
    # still offer the useful one.
    items = [f"Why is {subject} moving?"]
    if family == RISK:
        items.append("What would reduce this risk?")
    elif family == OPPORTUNITY:
        items.append("How large is this opportunity?")
    else:
        items.append(f"Where is {subject} heading?")
    if dims:
        items.append(f"Break {subject} down by {_humanize(dims[0])}")
    items.append(f"What is driving {subject}?")
    items.append("Which documents mention this?")
    items.append(f"When did {subject} start changing?")
    if len(dims) > 1:
        items.append(f"Compare {_humanize(dims[0])} against {_humanize(dims[1])}")
    return items[:max_items]


# ── Turning method envelopes into the facts an action needs ──────────────────


def extract_findings(intent: str, envelope: dict[str, Any]) -> dict[str, Any]:
    """Pull the action-relevant facts out of one method result.

    :func:`propose_actions` needs a small, stable vocabulary — which segment,
    which period, which driver, which direction — rather than each method's raw
    output shape. Unknown shapes yield ``{}`` so a method that reports something
    unexpected simply contributes nothing instead of breaking the card.
    """
    if not isinstance(envelope, dict):
        return {}
    results = envelope.get("results")
    if not isinstance(results, dict):
        return {}
    lowered = {str(k).lower(): v for k, v in results.items()}
    facts: dict[str, Any] = {}

    def _list(*keys: str) -> list[Any]:
        for key in keys:
            value = lowered.get(key)
            if isinstance(value, list) and value:
                return value
        return []

    def _num(*keys: str) -> float | None:
        for key in keys:
            value = lowered.get(key)
            if isinstance(value, int | float) and not isinstance(value, bool):
                return float(value)
        return None

    if intent in {"compare_multiple_groups", "compare_two_groups", "contribution_to_change"}:
        groups = _list("contributions", "groups", "drivers", "segments")
        top = _top_named(groups)
        if top:
            facts["top_segment"] = top[0]
            if top[1] is not None:
                facts["top_segment_share"] = top[1]
    elif intent == "detect_change_point":
        points = _list("change_points", "changepoints", "breaks")
        facts["change_point_count"] = len(points)
        label = _first_label(points)
        if label:
            facts["change_point_period"] = label
    elif intent == "detect_anomalies":
        facts["anomaly_count"] = len(_list("anomalies", "flagged", "outliers"))
    elif intent in {"continuous_prediction", "relationship_numeric", "relationship_monotonic"}:
        drivers = _list("coefficients", "drivers", "predictors")
        top = _top_named(drivers)
        if top:
            facts["top_driver"] = top[0]
    elif intent == "forecast_time_series":
        slope = _num("trend", "slope", "direction")
        if slope is not None:
            facts["forecast_direction"] = "worsening" if slope > 0 else "improving"
    elif intent in {"compare_periods", "compare_year_over_year", "compare_to_baseline"}:
        change = _num("relative_change", "percent_change", "pct_change")
        if change is not None:
            facts["period_change"] = change
    return facts


def _top_named(items: list[Any]) -> tuple[str, float | None] | None:
    """(name, magnitude) of the largest contributor in a list of dict rows."""
    best: tuple[str, float | None] | None = None
    best_mag = float("-inf")
    for item in items:
        if not isinstance(item, dict):
            continue
        name = next(
            (
                str(item[k])
                for k in ("group", "name", "label", "segment", "variable", "term")
                if item.get(k) is not None
            ),
            None,
        )
        if not name:
            continue
        magnitude = next(
            (
                float(item[k])
                for k in ("contribution", "share", "value", "estimate", "coefficient")
                if isinstance(item.get(k), int | float) and not isinstance(item.get(k), bool)
            ),
            None,
        )
        weight = abs(magnitude) if magnitude is not None else 0.0
        if weight > best_mag:
            best_mag = weight
            best = (name, magnitude)
    return best


def _first_label(items: list[Any]) -> str | None:
    for item in items:
        if isinstance(item, dict):
            for key in ("period", "date", "label", "index", "at"):
                if item.get(key) is not None:
                    return str(item[key])
        elif isinstance(item, str | int):
            return str(item)
    return None


def extract_markers(intent: str, envelope: dict[str, Any] | None) -> dict[str, Any]:
    """Point-level annotations the chart should draw, taken from the method.

    The renderer can re-derive "anomalies" itself with a 2-sigma rule, but that
    would mark *different* points than the method flagged — R's ``detect_anomalies``
    uses an ETS fit, so a point inside 2 sigma of the mean can still sit outside
    its own expected band. Marking a point the method did not flag is worse than
    marking nothing, so the indices travel with the result.

    Indices are normalised to **0-based** positions in the period-ordered series
    (R reports 1-based). Returns ``{}`` when the method exposes nothing to mark,
    so the chart simply renders unannotated.
    """
    results = (envelope or {}).get("results")
    if not isinstance(results, dict):
        return {}
    lowered = {str(k).lower(): v for k, v in results.items()}

    def _floats(*keys: str) -> list[float]:
        for key in keys:
            value = lowered.get(key)
            if isinstance(value, list) and value:
                out: list[float] = []
                for item in value:
                    if isinstance(item, int | float) and not isinstance(item, bool):
                        out.append(float(item))
                    else:
                        return []
                return out
        return []

    markers: dict[str, Any] = {}

    if intent == "detect_anomalies":
        raw = lowered.get("anomalies")
        indices: list[int] = []
        if isinstance(raw, list):
            for item in raw:
                # R emits bare 1-based positions; a dict form may carry an index.
                if isinstance(item, int | float) and not isinstance(item, bool):
                    indices.append(int(item) - 1)
                elif isinstance(item, dict):
                    for key in ("index", "position", "i"):
                        value = item.get(key)
                        if isinstance(value, int | float) and not isinstance(value, bool):
                            indices.append(int(value) - 1)
                            break
        indices = sorted({i for i in indices if i >= 0})
        if indices:
            markers["anomalyIndices"] = indices
        band = {
            key: _floats(key)
            for key in ("expected", "lower", "upper")
        }
        if all(band.values()) and len({len(v) for v in band.values()}) == 1:
            markers["band"] = band

    elif intent == "detect_change_point":
        points = lowered.get("change_points") or lowered.get("changepoints")
        if isinstance(points, list):
            for item in points:
                value = item.get("index") if isinstance(item, dict) else item
                if isinstance(value, int | float) and not isinstance(value, bool):
                    markers["changePointIndex"] = int(value) - 1
                    break

    return markers


#: Intents whose method needs raw rows but whose *chart* needs per-group totals.
GROUP_EVIDENCE_INTENTS = frozenset({"compare_multiple_groups", "compare_two_groups"})


def summarise_group_evidence(
    rows: list[dict[str, Any]],
    group_key: str,
    value_key: str,
    *,
    max_groups: int = 20,
) -> tuple[list[dict[str, Any]], list[str], int | None]:
    """Per-group averages for a group comparison, worst group first.

    A group comparison feeds *raw* rows to the method — Welch's ANOVA needs the
    within-group spread, not a pre-aggregated mean. Charting those same rows is
    what produced a wall of identical bars with the same work centre repeated
    down the axis: it was plotting individual records, not groups.

    The chart needs the opposite shape, so the rows are folded here into one
    entry per group, ranked by the measure. Ranking is what makes the chart
    answer "where is the problem" — the leading bar *is* the answer.

    Returns ``(rows, columns, marked_index)``; ``marked_index`` is the leading
    group, or ``None`` when the groups are too even for one to lead.
    """
    totals: dict[str, list[float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        group = row.get(group_key)
        value = row.get(value_key)
        if group is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        totals.setdefault(str(group), []).append(float(value))

    if len(totals) < 2:
        return [], [], None

    summary: list[dict[str, Any]] = [
        {
            group_key: group,
            value_key: round(sum(values) / len(values), 4),
            "observations": len(values),
        }
        for group, values in totals.items()
    ]
    summary.sort(key=lambda r: abs(float(cast(Any, r[value_key]))), reverse=True)
    summary = summary[:max_groups]

    # Only claim a leader when one actually leads. Marking the top bar of an
    # essentially flat ranking would point at noise.
    marked: int | None = None
    if len(summary) >= 2:
        top = abs(float(cast(Any, summary[0][value_key])))
        runner_up = abs(float(cast(Any, summary[1][value_key])))
        if top > 0 and (top - runner_up) / top >= 0.10:
            marked = 0

    return summary, [group_key, value_key, "observations"], marked


def describe_group_leader(
    summary: list[dict[str, Any]],
    group_key: str,
    value_key: str,
    *,
    marked: int | None,
) -> str:
    """One sentence naming the segment the problem sits in.

    "Groups differ significantly (p=0.000)" is a true statement that tells a
    plant manager nothing — it reports that the test rejected its null
    hypothesis, not where to go. This names the leading group, its level, and
    how far clear of the next one it is, which is the part someone can act on.

    Returns ``""`` when no group leads clearly enough to name one.
    """
    if marked is None or not summary or marked >= len(summary):
        return ""
    lead = summary[marked]
    name = lead.get(group_key)
    value = lead.get(value_key)
    if name is None or not isinstance(value, int | float) or isinstance(value, bool):
        return ""

    sentence = f"{name} leads at {float(value):,.4g} per record"
    runner_up = summary[marked + 1] if marked + 1 < len(summary) else None
    if runner_up:
        other = runner_up.get(value_key)
        if isinstance(other, int | float) and not isinstance(other, bool) and other:
            gap = (abs(float(value)) - abs(float(other))) / abs(float(other))
            if gap > 0:
                sentence += f", {gap:.0%} above {runner_up.get(group_key)}"
    n = lead.get("observations")
    if isinstance(n, int):
        sentence += f" (across {n} observations)"
    return sentence + "."
