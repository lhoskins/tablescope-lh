
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResolverCandidate:
    """One scored authorized source considered for a request."""

    source: str
    score: float
    matched_columns: list[str]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "score": round(self.score, 1),
            "matched_columns": self.matched_columns,
            "reason": self.reason,
        }


@dataclass
class ResolverResult:
    """Outcome of resolving a request onto authorized project sources."""

    status: str  # "resolved" | "no_match"
    preferred_sources: list[str] = field(default_factory=list)
    relevant_columns: list[str] = field(default_factory=list)
    intent: str = ""
    confidence: float = 0.0
    reason: str = ""
    candidates: list[ResolverCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "preferred_sources": self.preferred_sources,
            "relevant_columns": self.relevant_columns,
            "intent": self.intent,
            "confidence": round(self.confidence, 2),
            "reason": self.reason,
            "candidates": [c.to_dict() for c in self.candidates],
        }


@dataclass
class _Source:
    name: str
    columns: list[str]
    kind: str  # "table" | "db" | "query"
    description: str = ""
