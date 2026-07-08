"""Declared Intent Engine — a hint, not an authority.

A single, local, deterministic heuristic classifier that turns a user question
(optionally with the profile of an executed result set) into a declared routing
decision. Until now the ask path relied on three independent, uncoordinated
try/fallback code paths with no declared classifier anywhere in the repo; this
consolidates the routing *signal* into one place.

Design constraints (Devin ASK §5, plan §6):
- **Never calls the LLM.** Consistent with "Tablescope decides, not the LLM".
- **A hint, layered on the existing try-then-fallback backbone — never an
  authority.** A misclassification may only produce a possibly-suboptimal but
  safe fallback (e.g. an unnecessary SQL attempt that then degrades to prose),
  never a hard failure.
- ``confidence`` is a heuristic in ``[0, 1]``, NOT a calibrated probability, and
  must not be presented in the UI as one.
- ``analysisIntent`` reuses the Method Engine's own intent inference so the two
  engines agree, and feeds the Method Engine's Stage-B selector.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.services.analytical_method_engine.intent import infer_intent


class ResponseMode(str, Enum):
    """How the answer should be produced."""

    STRUCTURED_DATA = "structured_data"  # try SQL over an authorized source
    PROSE = "prose"  # documents + knowledge-graph free-text answer


# Quantitative / aggregation phrasing -> the answer wants executed data.
_DATA_SIGNALS = re.compile(
    r"\b(how many|how much|count|number of|total|sum|average|avg|mean|median|"
    r"top|bottom|rank|ranking|trend|over time|by (?:month|quarter|year|week|day|"
    r"region|category|supplier|vendor|product|type|segment|customer|status)|"
    r"per\s+(?:unit|month|year|quarter|week|day|hour|supplier|vendor|product|"
    r"category|region|customer|order|item|capita|employee|store|warehouse)|"
    r"compare|comparison|highest|lowest|most|least|growth|"
    r"rate|percentage|percent|share|distribution|correlat|breakdown|"
    r"group by|year over year|yoy|month over month)\b"
)

# Policy / document phrasing -> the answer lives in documents, not a table.
_DOC_SIGNALS = re.compile(
    r"\b(policy|policies|procedure|procedures|guideline|guidelines|clause|"
    r"contract|agreement|compliance|according to|documented|document|handbook|"
    r"regulation|regulations|standard|sop|terms|requirement|requirements|"
    r"obligation|obligations)\b"
)

# Explanatory phrasing -> prose, unless clearly quantitative.
_EXPLAIN_SIGNALS = re.compile(
    r"\b(why|how do|how does|how should|how can|explain|describe|"
    r"summar(?:y|ise|ize|ising|izing)|what does|what is the |recommend|"
    r"should we|advice|advise|interpret|meaning|means)\b"
)

# Relationship / entity phrasing -> knowledge-graph grounding is relevant.
_KG_SIGNALS = re.compile(
    r"\b(relationship between|related to|connected to|linked to|"
    r"depends? on|dependency|dependencies|associat(?:e|ed|ion) between|"
    r"network of|tied to|impact(?:s|ed)? by)\b"
)


@dataclass(frozen=True)
class IntentDecision:
    """The declared routing decision for one question.

    ``analysis_intent`` is one of the Method Engine's intents (or ``None`` when
    nothing statistical is clearly requested / no profile was supplied).
    """

    response_mode: ResponseMode
    analysis_intent: str | None
    requires_sql: bool
    requires_documents: bool
    requires_knowledge_graph: bool
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "responseMode": self.response_mode.value,
            "analysisIntent": self.analysis_intent,
            "requiresSql": self.requires_sql,
            "requiresDocuments": self.requires_documents,
            "requiresKnowledgeGraph": self.requires_knowledge_graph,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def classify_intent(
    question: str, profile: dict[str, Any] | None = None
) -> IntentDecision:
    """Classify a question into a declared routing decision.

    Pure and deterministic. When ``profile`` (the executed result set's shape
    from the Method Engine's Stage-A profiler) is supplied, ``analysis_intent``
    is inferred with the same logic the Method Engine uses so the two agree.
    """
    q = (question or "").strip().lower()
    analysis_intent = infer_intent(question, profile) if profile else None

    if not q:
        return IntentDecision(
            ResponseMode.PROSE, analysis_intent, False, True, False, 0.2,
            "empty question — default to prose",
        )

    data = bool(_DATA_SIGNALS.search(q))
    doc = bool(_DOC_SIGNALS.search(q))
    explain = bool(_EXPLAIN_SIGNALS.search(q))
    kg = bool(_KG_SIGNALS.search(q))

    if data:
        # Quantitative phrasing wins. If policy/document words are also present
        # the signal is mixed, so lower the confidence but still try data first.
        mode = ResponseMode.STRUCTURED_DATA
        requires_sql = True
        confidence = 0.6 if doc else 0.8
        reason = (
            "quantitative phrasing with document terms — data-first, low confidence"
            if doc else "quantitative/aggregation phrasing"
        )
    elif doc or explain:
        mode = ResponseMode.PROSE
        requires_sql = False
        confidence = 0.75 if doc else 0.55
        reason = "policy/document phrasing" if doc else "explanatory phrasing"
    else:
        # No strong signal: default to the existing data-first backbone at low
        # confidence so the try-then-fallback safety net still governs.
        mode = ResponseMode.STRUCTURED_DATA
        requires_sql = True
        confidence = 0.4
        reason = "no strong signal — default to data-first backbone"

    requires_documents = doc or explain or mode is ResponseMode.PROSE
    return IntentDecision(
        response_mode=mode,
        analysis_intent=analysis_intent,
        requires_sql=requires_sql,
        requires_documents=requires_documents,
        requires_knowledge_graph=kg,
        confidence=round(confidence, 2),
        reason=reason,
    )
