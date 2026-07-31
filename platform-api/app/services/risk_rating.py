"""Versioned likelihood x impact risk-rating.

The server is authoritative for risk severity; the client may preview a computed
value but must never set it directly. Versioned so a later change to the formula
does not silently reinterpret historical ratings — existing rows keep the
version they were rated under.

Likelihood carries 5 levels and impact carries 7 (matching the validated values
in project_context.py) — an asymmetric hand-written 5x5 grid was the original
draft and silently failed to rate "insignificant" or "catastrophic" impact.
A normalized product avoids that by construction: every (likelihood, impact)
pair maps to some bucket.
"""

from __future__ import annotations

RATING_MATRIX_VERSION = 1

_LIKELIHOOD_ORDER = {"rare": 1, "unlikely": 2, "possible": 3, "likely": 4, "almost_certain": 5}
_IMPACT_ORDER = {
    "negligible": 1,
    "insignificant": 2,
    "minor": 3,
    "moderate": 4,
    "major": 5,
    "severe": 6,
    "catastrophic": 7,
}
# Normalized score = (likelihood/5) * (impact/7), range (0, 1]. Thresholds
# chosen so a "possible" x "moderate" risk (the middle of both scales) lands
# in "medium".
_THRESHOLDS = (  # (max_score_exclusive_upper_bound, severity)
    (0.20, "low"),
    (0.45, "medium"),
    (0.70, "high"),
    (1.01, "critical"),  # 1.01 so a perfect 1.0 is included
)


def compute_severity(likelihood: str | None, impact: str | None) -> str | None:
    """Return the computed rating, or None if either input is missing/unrecognised."""
    li = _LIKELIHOOD_ORDER.get(likelihood or "")
    im = _IMPACT_ORDER.get(impact or "")
    if li is None or im is None:
        return None
    score = (li / 5) * (im / 7)
    for upper_bound, severity in _THRESHOLDS:
        if score < upper_bound:
            return severity
    return "critical"
