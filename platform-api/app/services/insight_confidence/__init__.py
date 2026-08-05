
from __future__ import annotations

from .evaluator import evaluate_confidence as evaluate_confidence
from .scoring_helpers import _basis_from_factors as _basis_from_factors
from .scoring_helpers import _coverage_fraction as _coverage_fraction
from .scoring_helpers import _gap_text as _gap_text
from .scoring_helpers import _level_for_score as _level_for_score
from .scoring_helpers import _pct_non_null as _pct_non_null
from .scoring_helpers import _to_float as _to_float
from .types import _CAP_DOCUMENT_ONLY as _CAP_DOCUMENT_ONLY
from .types import _CAP_FEW_ROWS as _CAP_FEW_ROWS
from .types import _CAP_HIGH_JOIN_RISK as _CAP_HIGH_JOIN_RISK
from .types import _CAP_TENTATIVE_METHOD as _CAP_TENTATIVE_METHOD
from .types import _HIGH as _HIGH
from .types import _MEDIUM as _MEDIUM
from .types import CONFIDENCE_VERSION as CONFIDENCE_VERSION
from .types import ConfidenceEvaluation as ConfidenceEvaluation
from .types import ConfidenceFactor as ConfidenceFactor

"""Evidence-based confidence evaluation for generated insight cards.

Confidence is derived from deterministic factors tied to the quality of the
evidence, not from row count alone. The evaluator returns a structured
confidence package (score, level, basis, factors, caps, gaps) that the Explain
panel can render without guessing.
"""
