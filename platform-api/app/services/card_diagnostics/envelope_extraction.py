
from __future__ import annotations

from typing import Any

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
