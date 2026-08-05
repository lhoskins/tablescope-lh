from __future__ import annotations

from typing import Any

from app.services.chart_catalog import (
    fit_ranked,
)

from .catalog import _WEAK_FIT_THRESHOLD, _catalog_chart_type, _catalog_facts, _catalog_shape, _normalize_hint
from .heuristics import (
    _detect_semantic_roles,
    _is_monotonic_decreasing,
    _looks_like_id_labels,
    _looks_like_metric_label,
    _looks_like_share,
    detect_value_format,
)
from .shape import (
    _BAR_RANK_CAP,
    _HORIZONTAL_BAR_THRESHOLD,
    _column_values,
    _dimension_cardinality,
    _is_period_dimension,
    _primary_dimension,
    _rows_as_dicts,
    _to_float,
    derive_shape,
)
from .types import ChartType, ValueFormat, VizCandidate, VizDecision, _Shape


def _categorical_bar(
    label_col: str,
    value_col: str,
    vfmt: ValueFormat,
    label_card: int,
    labels: list[str],
    *,
    confidence: float,
) -> VizDecision:
    """Bar decision for a category comparison, made readable for many categories.

    Many distinct or id-like categories flip to a horizontal bar (labels stack
    down the y-axis); beyond :data:`_BAR_RANK_CAP` the decision also asks the
    surface to rank by the measure and keep only the top N, so the chart shows
    the leaders instead of an unreadable wall of ticks.
    """
    many = label_card > _HORIZONTAL_BAR_THRESHOLD or _looks_like_id_labels(labels)
    top_n = _BAR_RANK_CAP if label_card > _BAR_RANK_CAP else None
    if top_n is not None:
        reason = (
            f"{label_card} categories — ranked top {top_n} as a horizontal bar "
            "so the axis stays readable."
        )
    elif many:
        reason = "Several categories — horizontal bar for readable labels."
    else:
        reason = "Category comparison."
    return VizDecision(
        ChartType.BAR,
        chart_style="horizontal_bar" if many else "",
        x_field=label_col,
        y_field=value_col,
        value_format=vfmt,
        top_n=top_n,
        reason=reason,
        confidence=confidence,
    )


def _candidate(
    chart_type: ChartType,
    score: float,
    *,
    x_field: str | None = None,
    y_field: str | None = None,
    y2_field: str | None = None,
    chart_style: str = "",
    value_format: ValueFormat = "number",
    top_n: int | None = None,
    reason: str = "",
    supported: bool = True,
    unsupported_reason: str = "",
) -> VizCandidate:
    return VizCandidate(
        decision=VizDecision(
            chart_type=chart_type,
            chart_style=chart_style,
            x_field=x_field,
            y_field=y_field,
            y2_field=y2_field,
            value_format=value_format,
            top_n=top_n,
            reason=reason,
            confidence=round(score, 3),
        ),
        score=score,
        supported=supported,
        unsupported_reason=unsupported_reason,
    )


def recommend_visualizations(
    columns: list[str],
    rows: list[Any],
    *,
    profile: dict[str, Any] | None = None,
    intent_hint: str | None = None,
    semantic_roles: dict[str, str | None] | None = None,
    analytical_evidence: dict[str, Any] | None = None,
    method_envelope: dict[str, Any] | None = None,
    limit: int = 8,
) -> list[VizCandidate]:
    """Return a ranked list of supported visualization candidates for a result set.

    ``intent_hint`` is honoured when the shape supports it; the data always wins.
    ``semantic_roles`` and ``analytical_evidence`` allow the method engine to
    suggest richer families (radar, sankey, funnel, etc.) with explicit role
    mappings.
    ``method_envelope`` may carry analytical results (e.g. distribution groups,
    OHLC roles) that unlock richer families.
    """
    if not columns or not rows:
        return [_candidate(ChartType.TABLE, 0.2, reason="No data to plot.")]

    dict_rows = _rows_as_dicts(columns, rows)
    shape = derive_shape(columns, dict_rows, profile)
    hint = _normalize_hint(intent_hint)
    roles = semantic_roles or _detect_semantic_roles(columns, dict_rows)

    # Forced/hinted families when shape supports them.
    if hint and hint not in ("line", "area", "combo", "scatter", "kpi", "table"):
        forced = _hint_candidate(columns, dict_rows, shape, hint, roles)
        if forced:
            return [forced, *_fallback_candidates(shape, roles, exclude={hint})]

    candidates: list[VizCandidate] = []

    # 1) Single-row scalar summary -> KPI (or table if no measure).
    # A single result row with one numeric measure and no real categorical
    # dimension (or only a metric-name label dimension) is a headline metric.
    # Time columns are excluded because a lone time point is still a series
    # intent and should prefer line/area/combo.
    if shape.row_count == 1 and shape.measures and not shape.time_columns:
        non_time_label_cols = [c for c in shape.dimensions if c not in shape.time_columns]
        scalar_label = (
            len(non_time_label_cols) == 1 and _looks_like_metric_label(non_time_label_cols[0])
        )
        if not non_time_label_cols or scalar_label:
            metric = shape.measures[0]
            candidates.append(
                _candidate(
                    ChartType.KPI,
                    0.95,
                    y_field=metric,
                    value_format=detect_value_format(metric, _column_values(dict_rows, metric)),
                    reason="Single-row scalar summary — headline metric as a KPI tile.",
                )
            )
            candidates.append(
                _candidate(
                    ChartType.GAUGE,
                    0.85,
                    y_field=metric,
                    value_format=detect_value_format(metric, _column_values(dict_rows, metric)),
                    reason="Single scalar value shown as a radial gauge.",
                )
            )
            candidates.append(_candidate(ChartType.TABLE, 0.1, reason="Single row — table fallback."))
            return sorted(candidates, key=lambda c: c.score, reverse=True)

    if shape.row_count == 1 and not shape.measures:
        return [_candidate(ChartType.TABLE, 0.1, reason="Single row with no numeric metric.")]

    # No measures at all -> table.
    if not shape.measures:
        return [_candidate(ChartType.TABLE, 0.9, reason="No numeric measure to plot — showing detail rows.")]

    label_col = _primary_dimension(shape)
    value_col = shape.measures[0]
    values = _column_values(dict_rows, value_col, limit=200)
    vfmt = detect_value_format(value_col, values)
    label_card = _dimension_cardinality(shape, label_col)
    all_positive = all((f := _to_float(v)) is None or f >= 0 for v in values)
    labels = [str(v) for v in _column_values(dict_rows, label_col, limit=50)] if label_col else []
    label_is_period = label_col is not None and _is_period_dimension(shape, label_col)

    # 2) Sankey: explicit source/target/value roles.
    source_col = roles.get("source")
    target_col = roles.get("target")
    value_col_for_flow = roles.get("value")
    if source_col and target_col and value_col_for_flow:
        candidates.append(
            _candidate(
                ChartType.SANKEY,
                0.92,
                x_field=source_col,
                y_field=target_col,
                value_format=detect_value_format(value_col_for_flow, _column_values(dict_rows, value_col_for_flow, 50)),
                reason=f"Source→target flow: {source_col} → {target_col} weighted by {value_col_for_flow}.",
            )
        )

    # 3) Time series -> line / area / combo.
    is_time = bool(shape.time_columns) or (label_col is not None and _is_period_dimension(shape, label_col))
    time_col = shape.time_columns[0] if shape.time_columns else label_col
    if is_time and time_col:
        if len(shape.measures) >= 2:
            candidates.append(
                _candidate(
                    ChartType.COMBO,
                    0.92,
                    x_field=time_col,
                    y_field=shape.measures[0],
                    y2_field=shape.measures[1],
                    value_format=vfmt,
                    reason="Two metrics over a shared time axis — combo (bar + line).",
                )
            )
            candidates.append(
                _candidate(
                    ChartType.LINE,
                    0.75,
                    x_field=time_col,
                    y_field=value_col,
                    value_format=vfmt,
                    reason="Ordered time-period labels — trend over time.",
                )
            )
            candidates.append(
                _candidate(
                    ChartType.AREA,
                    0.6,
                    x_field=time_col,
                    y_field=value_col,
                    value_format=vfmt,
                    reason="Cumulative or volume trend over time.",
                )
            )
        else:
            candidates.append(
                _candidate(
                    ChartType.LINE,
                    0.92,
                    x_field=time_col,
                    y_field=value_col,
                    value_format=vfmt,
                    reason="Ordered time-period labels — trend over time.",
                )
            )
            candidates.append(
                _candidate(
                    ChartType.AREA,
                    0.68,
                    x_field=time_col,
                    y_field=value_col,
                    value_format=vfmt,
                    reason="Cumulative or volume trend over time.",
                )
            )

    # Gauge is only appropriate for a single-row scalar summary; it is handled
    # in branch (1). Multi-point time series should never collapse to a gauge.

    # 3a) Time-series bar: a period axis is valid as a simple bar chart, but
    # it is *not* a category ranking and must not use top-N capping.
    if is_time and label_col is not None:
        candidates.append(
            _candidate(
                ChartType.BAR,
                0.45,
                x_field=label_col,
                y_field=value_col,
                value_format=vfmt,
                reason="Time-series values shown as bars for each period.",
            )
        )

    # 4) Two numeric measures -> scatter / effect scatter.
    # A categorical label is fine as a point name, but a period axis should prefer
    # the time-series families above.
    if len(shape.measures) >= 2 and not is_time:
        candidates.append(
            _candidate(
                ChartType.SCATTER,
                0.88,
                x_field=shape.measures[0],
                y_field=shape.measures[1],
                value_format=vfmt,
                reason="Two numeric measures with no category — correlation scatter.",
            )
        )
        candidates.append(
            _candidate(
                ChartType.EFFECT_SCATTER,
                0.6,
                x_field=shape.measures[0],
                y_field=shape.measures[1],
                value_format=vfmt,
                reason="Emphasize individual observations with ripple effects.",
            )
        )

    # 4b) Heatmap: two categorical dimensions and a numeric measure.
    if len(shape.dimensions) >= 2 and len(shape.measures) >= 1:
        non_period_dims = [c for c in shape.dimensions if not _is_period_dimension(shape, c)]
        dims = non_period_dims if len(non_period_dims) >= 2 else shape.dimensions[:2]
        if len(dims) >= 2:
            x_dim, y_dim = dims[0], dims[1]
            measure = shape.measures[0]
            candidates.append(
                _candidate(
                    ChartType.HEATMAP,
                    0.74,
                    x_field=x_dim,
                    y_field=measure,
                    y2_field=y_dim,
                    value_format=detect_value_format(measure, _column_values(dict_rows, measure, 50)),
                    reason=f"Two dimensions ({x_dim}, {y_dim}) and a measure ({measure}) — heatmap.",
                )
            )

    # 5) Funnel: stage-like labels and monotonically decreasing values.
    stage_col = roles.get("stage")
    if stage_col and label_col == stage_col and all_positive:
        stage_values = [
            v
            for v in [_to_float(r.get(stage_col)) for r in dict_rows if isinstance(r, dict)]
            if v is not None
        ]
        if stage_values and _is_monotonic_decreasing(stage_values):
            candidates.append(
                _candidate(
                    ChartType.FUNNEL,
                    0.85,
                    x_field=stage_col,
                    y_field=value_col,
                    value_format=vfmt,
                    reason="Stage progression with decreasing values — funnel.",
                )
            )

    # 6) Radar / radial bar / treemap / funnel / pie / bar for genuine category axes only.
    # A period/time axis must not masquerade as categories (e.g. 24 months becoming
    # "24 categories" in a ranked horizontal bar, or a rate metric triggering
    # radial_bar "by category"). Time-series shapes are handled above.
    if label_col is not None and not label_is_period:
        # Radar: 3-8 numeric measures per entity, or pivoted scorecard.
        if len(shape.measures) >= 3 and 1 <= label_card <= 6:
            candidates.append(
                _candidate(
                    ChartType.RADAR,
                    0.65,
                    x_field=label_col,
                    y_field=value_col,
                    value_format=vfmt,
                    reason="Multiple measures compared across a few entities — radar scorecard.",
                )
            )

        # Radial bar: percentage-to-target/rate values (must be non-negative).
        rate_col = roles.get("rate")
        if rate_col:
            rate_values = _column_values(dict_rows, rate_col, 200)
            rate_positive = all((f := _to_float(v)) is None or f >= 0 for v in rate_values)
            if rate_positive:
                candidates.append(
                    _candidate(
                        ChartType.RADIAL_BAR,
                        0.7,
                        x_field=label_col,
                        y_field=rate_col,
                        value_format="percent",
                        reason="Percentage-to-target metrics by category — radial bar.",
                    )
                )

        # Treemap: hierarchical group + value.
        group_col = roles.get("group")
        if group_col and group_col != label_col and all_positive:
            candidates.append(
                _candidate(
                    ChartType.TREEMAP,
                    0.68,
                    x_field=label_col,
                    y_field=value_col,
                    value_format=vfmt,
                    reason=f"Hierarchical part-to-whole by {group_col} — treemap.",
                )
            )

        # Part-of-a-whole -> pie/donut.
        if _looks_like_share(label_col, label_card, all_positive):
            candidates.append(
                _candidate(
                    ChartType.PIE,
                    0.82,
                    chart_style="donut",
                    x_field=label_col,
                    y_field=value_col,
                    value_format=vfmt,
                    reason="A few positive categories of a whole — share breakdown.",
                )
            )

        # Categorical comparison -> bar.
        many = label_card > _HORIZONTAL_BAR_THRESHOLD or _looks_like_id_labels(labels)
        top_n = _BAR_RANK_CAP if label_card > _BAR_RANK_CAP else None
        bar_reason = (
            f"{label_card} categories — ranked top {top_n} as a horizontal bar so the axis stays readable."
            if top_n else (
                "Several categories — horizontal bar for readable labels."
                if many else "Category comparison."
            )
        )
        bar_style = "horizontal_bar" if many else ""
        candidates.append(
            _candidate(
                ChartType.BAR,
                0.78,
                chart_style=bar_style,
                x_field=label_col,
                y_field=value_col,
                value_format=vfmt,
                top_n=top_n,
                reason=bar_reason,
            )
        )

        # Additional compatible families for positive categorical data (non-time only).
        if not is_time:
            if 2 <= label_card <= 8:
                candidates.append(
                    _candidate(
                        ChartType.RADAR,
                        0.55,
                        x_field=label_col,
                        y_field=value_col,
                        value_format=vfmt,
                        reason="Multi-metric comparison of a few entities — radar scorecard.",
                    )
                )
            if all_positive and label_card >= 2:
                candidates.append(
                    _candidate(
                        ChartType.FUNNEL,
                        0.54,
                        x_field=label_col,
                        y_field=value_col,
                        value_format=vfmt,
                        reason="Stage-like or ranked categories — funnel.",
                    )
                )
                candidates.append(
                    _candidate(
                        ChartType.TREEMAP,
                        0.5,
                        x_field=label_col,
                        y_field=value_col,
                        value_format=vfmt,
                        reason="Hierarchical part-to-whole by category — treemap.",
                    )
                )
            if all_positive and 2 <= label_card <= 12:
                candidates.append(
                    _candidate(
                        ChartType.RADIAL_BAR,
                        0.52,
                        x_field=label_col,
                        y_field=value_col,
                        value_format=vfmt,
                        reason="Relative size of categories around a center — radial bar.",
                    )
                )

    # Fallback table.
    candidates.append(_candidate(ChartType.TABLE, 0.15, reason="No clear chart shape — showing detail rows."))

    # Deduplicate by chart type + style, then enforce family diversity and cap.
    seen: set[tuple[str, str]] = set()
    unique: list[VizCandidate] = []
    for c in sorted(candidates, key=lambda x: x.score, reverse=True):
        key = (c.decision.chart_type.value, c.decision.chart_style)
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)

    # The markdown catalog is the hard eligibility gate: an inline branch can
    # propose a family, but only catalog-eligible families survive. This fixes
    # period/category leaks (e.g. 24 months being treated as 24 categories) and
    # keeps gated families (map) from surfacing.
    catalog_shape = _catalog_shape(shape, dict_rows, roles)
    catalog_facts = _catalog_facts(shape, dict_rows)
    # Per-dataset fit confidence (not just base eligibility) decides the order:
    # a family that is *eligible* for two dimensions may still be a poor fit when
    # a dimension is id-like (400 categories make an unreadable heatmap).
    fit_by_family = {
        rule.family: (rule, confidence)
        for rule, confidence in fit_ranked(catalog_shape, catalog_facts)
    }
    catalog_rules = {family: rule for family, (rule, _) in fit_by_family.items()}
    catalog_ok = set(catalog_rules) | {"table"}
    filtered: list[VizCandidate] = []
    for c in unique:
        family = c.decision.chart_type.value
        if family not in catalog_ok:
            continue
        entry = fit_by_family.get(family)
        if entry is not None:
            # Blend: the inline branch contributes *semantics* the catalog
            # cannot see from shape alone (part-of-whole, id-like labels, rate
            # columns); the catalog contributes *per-dataset fit* the inline
            # branch ignores (row count, cardinalities, specificity). Applying
            # the catalog's fit ratio to the inline score keeps both: a
            # semantically-right family stays on top, and any family sinks when
            # this dataset's shape makes it a poor fit.
            rule, confidence = entry
            fit_ratio = confidence / rule.score if rule.score > 0 else 0.0
            c.score = round(min(c.score * fit_ratio, 1.0), 4)
            c.decision.confidence = c.score
        filtered.append(c)

    # Promote catalog-eligible families the inline branches never proposed, so
    # editing the markdown is enough to surface a new chart family. Families
    # that render as a parent type's variant (histogram, waterfall, bubble,
    # bump, calendar heatmap) are promoted through that parent.
    # Dedupe by family: if an inline branch already produced this ChartType it
    # picked a considered style (e.g. horizontal_bar for id-like labels), so the
    # catalog must not add a bare duplicate that outranks it.
    existing_types = {c.decision.chart_type.value for c in filtered}
    for family, rule in catalog_rules.items():
        confidence = fit_by_family[family][1]
        if confidence < 0.5:
            continue
        resolved = _catalog_chart_type(family)
        if resolved is None:
            continue
        chart_type, chart_style = resolved
        if chart_type.value in existing_types:
            continue
        existing_types.add(chart_type.value)
        filtered.append(
            _candidate(
                chart_type,
                confidence,
                chart_style=chart_style,
                reason=rule.guidance.split(".")[0] if rule.guidance else f"{family} from catalog",
            )
        )

    # When nothing fits the shape well, the detail table is the honest answer
    # rather than the least-bad chart.
    best_chart = max(
        (c.score for c in filtered if c.decision.chart_type != ChartType.TABLE),
        default=0.0,
    )
    if best_chart < _WEAK_FIT_THRESHOLD:
        for c in filtered:
            if c.decision.chart_type == ChartType.TABLE:
                c.score = max(c.score, best_chart + 0.05)
                c.decision.confidence = c.score

    return _diverse_top_n(filtered, limit)


def _hint_candidate(
    columns: list[str],
    rows: list[dict[str, Any]],
    shape: _Shape,
    hint: str,
    roles: dict[str, str | None],
) -> VizCandidate | None:
    """Build a single candidate for an explicit hint when the shape supports it."""
    if not shape.measures:
        return None
    value_col = shape.measures[0]
    label_col = _primary_dimension(shape)
    vfmt = detect_value_format(value_col, _column_values(rows, value_col, 50))
    label_card = _dimension_cardinality(shape, label_col)
    all_positive = all((f := _to_float(v)) is None or f >= 0 for v in _column_values(rows, value_col, 200))
    label_is_period = label_col is not None and _is_period_dimension(shape, label_col)

    if hint == "pie" and label_col is not None and not label_is_period and all_positive and 2 <= label_card <= 8:
        return _candidate(
            ChartType.PIE,
            0.82,
            chart_style="donut",
            x_field=label_col,
            y_field=value_col,
            value_format=vfmt,
            reason="Explicit share breakdown.",
        )
    if hint == "heatmap":
        if len(shape.dimensions) >= 2 and len(shape.measures) >= 1:
            non_period = [c for c in shape.dimensions if not _is_period_dimension(shape, c)]
            dims = non_period if len(non_period) >= 2 else shape.dimensions[:2]
            if len(dims) >= 2:
                return _candidate(
                    ChartType.HEATMAP,
                    0.8,
                    x_field=dims[0],
                    y_field=shape.measures[0],
                    y2_field=dims[1],
                    value_format=detect_value_format(shape.measures[0], _column_values(rows, shape.measures[0], 50)),
                    reason="Explicit heatmap request for two dimensions and a measure.",
                )
    if hint == "radar" and label_col is not None and not label_is_period:
        return _candidate(
            ChartType.RADAR,
            0.75,
            x_field=label_col,
            y_field=value_col,
            value_format=vfmt,
            reason="Explicit radar request.",
        )
    if hint == "treemap" and label_col is not None and not label_is_period:
        return _candidate(
            ChartType.TREEMAP,
            0.75,
            x_field=label_col,
            y_field=value_col,
            value_format=vfmt,
            reason="Explicit treemap request.",
        )
    if hint == "funnel" and label_col is not None and not label_is_period:
        return _candidate(
            ChartType.FUNNEL,
            0.75,
            x_field=label_col,
            y_field=value_col,
            value_format=vfmt,
            reason="Explicit funnel request.",
        )
    if hint == "sankey":
        source_col = roles.get("source") or label_col
        target_col = roles.get("target")
        value_col_flow = roles.get("value") or value_col
        if source_col and target_col:
            return _candidate(
                ChartType.SANKEY,
                0.85,
                x_field=source_col,
                y_field=target_col,
                value_format=detect_value_format(value_col_flow, _column_values(rows, value_col_flow, 50)),
                reason="Explicit sankey request.",
            )
    if hint == "radial_bar" and label_col is not None and not label_is_period and all_positive:
        rate_col = roles.get("rate") or value_col
        rate_values = _column_values(rows, rate_col, 200)
        rate_positive = all((f := _to_float(v)) is None or f >= 0 for v in rate_values)
        if rate_positive:
            return _candidate(
                ChartType.RADIAL_BAR,
                0.75,
                x_field=label_col,
                y_field=rate_col,
                value_format="percent",
                reason="Explicit radial bar request.",
            )
    if hint == "bar" and label_col is not None:
        return _candidate(
            ChartType.BAR,
            0.78,
            x_field=label_col,
            y_field=value_col,
            value_format=vfmt,
            reason="Explicit bar request.",
        )
    if hint == "gauge" and shape.row_count == 1 and shape.measures:
        return _candidate(
            ChartType.GAUGE,
            0.78,
            y_field=value_col,
            value_format=vfmt,
            reason="Explicit gauge request — single headline value.",
        )
    if hint == "effect_scatter" and len(shape.measures) >= 2:
        return _candidate(
            ChartType.EFFECT_SCATTER,
            0.75,
            x_field=shape.measures[0],
            y_field=shape.measures[1],
            value_format=vfmt,
            reason="Explicit effect-scatter request — emphasize individual points.",
        )
    # The explicit hint cannot be honoured by this data shape; fall through to
    # the shape-driven ranking so the data always wins.
    return None


def _fallback_candidates(
    shape: _Shape,
    roles: dict[str, str | None],
    exclude: set[str],
) -> list[VizCandidate]:
    """Return the ranked candidates excluding the already-forced hint."""
    # Build a minimal columns/rows set and call the main recommender, filtering.
    if not shape.columns:
        return []
    # Rebuild a few representative rows from shape metadata is not enough, so we
    # return an empty list; the caller already has the winner it asked for.
    return []


def _diverse_top_n(candidates: list[VizCandidate], limit: int) -> list[VizCandidate]:
    """Return the top ``limit`` candidates while maximising family diversity.

    Each ``ChartType`` is treated as a family. The highest-scoring candidate from
    each family is kept first; remaining slots are filled with the next-best
    candidates. This prevents a single family (e.g. bar) from filling all six
    suggestion slots.
    """
    sorted_by_score = sorted(candidates, key=lambda c: c.score, reverse=True)
    seen_families: set[str] = set()
    first_pass: list[VizCandidate] = []
    second_pass: list[VizCandidate] = []
    for c in sorted_by_score:
        family = c.decision.chart_type.value
        if family in seen_families:
            second_pass.append(c)
        else:
            seen_families.add(family)
            first_pass.append(c)
    diverse = first_pass + second_pass
    return diverse[:limit]


def rank_visualizations(
    columns: list[str],
    rows: list[Any],
    *,
    profile: dict[str, Any] | None = None,
    intent_hint: str | None = None,
    semantic_roles: dict[str, str | None] | None = None,
    analytical_evidence: dict[str, Any] | None = None,
    method_envelope: dict[str, Any] | None = None,
    limit: int = 6,
) -> list[VizCandidate]:
    """Rank the top ``limit`` diverse, data-shape-driven chart families.

    ``intent_hint`` and ``method_envelope`` only bias scores; the data shape
    decides which families are eligible.
    """
    return recommend_visualizations(
        columns,
        rows,
        profile=profile,
        intent_hint=intent_hint,
        semantic_roles=semantic_roles,
        analytical_evidence=analytical_evidence,
        method_envelope=method_envelope,
        limit=limit,
    )


def select_visualization(
    columns: list[str],
    rows: list[Any],
    *,
    profile: dict[str, Any] | None = None,
    intent_hint: str | None = None,
) -> VizDecision:
    """Choose the best renderable chart for a result set (deterministic).

    This is the legacy single-decision entry point; it delegates to
    :func:`rank_visualizations` and returns the highest-scoring candidate.
    """
    candidates = rank_visualizations(columns, rows, profile=profile, intent_hint=intent_hint, limit=6)
    if not candidates:
        return VizDecision(ChartType.TABLE, reason="No data to plot.", confidence=1.0)
    top = candidates[0]
    return top.decision
