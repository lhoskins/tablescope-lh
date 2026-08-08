
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

CONFIDENCE_VERSION = 1


# Score thresholds.
_HIGH = 0.80
_MEDIUM = 0.60

# Hard caps applied after the weighted sum.
_CAP_DOCUMENT_ONLY = 0.50
_CAP_FEW_ROWS = 0.49
_CAP_TENTATIVE_METHOD = 0.74
_CAP_HIGH_JOIN_RISK = 0.50


@dataclass
class ConfidenceFactor:
    code: str
    label: str
    status: str  # passed | partial | failed | not_applicable
    score: float  # 0..1
    weight: float
    evidence: str


@dataclass
class ConfidenceEvaluation:
    version: int = CONFIDENCE_VERSION
    score: float = 0.0
    level: str = "low"  # low | medium | high
    basis: str = ""
    factors: list[ConfidenceFactor] = field(default_factory=list)
    caps: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    what_would_increase_confidence: str = ""
    evaluator_version: str = "evidence-v1"
    evaluated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
