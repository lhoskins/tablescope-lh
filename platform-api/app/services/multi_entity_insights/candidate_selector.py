"""Multi-source-first candidate discovery and ranking.

Given a project schema, relationship hints, and a user question, the selector
discovers table combinations that can safely compare two or three named
entities. It prefers combinations with two or three related sources and only
falls back to a single source when no safe multi-source candidate survives.
"""

from __future__ import annotations

from itertools import combinations, pairwise
from typing import Any

from app.services.multi_entity_insights.contract import (
    EntitySpec,
    MeasureSpec,
    MultiEntityPlan,
    RelationshipSpec,
    SourceSpec,
    SourceStrategy,
    TimeSpec,
)
from app.services.multi_entity_insights.intent import infer_multi_entity_intent

_MEASURE_KEYWORDS = [
    "amount", "cost", "count", "defect", "demand", "duration", "forecast",
    "hours", "num", "price", "qty", "quantity", "rate", "revenue", "score",
    "scrap", "shipped", "spend", "sum", "total", "units", "usage", "utilization",
    "value", "volume",
]

_PERIOD_KEYWORDS = ["month", "period", "quarter", "week", "year", "date", "time"]

_ENTITY_TYPE_KEYWORDS: dict[str, list[str]] = {
    "supplier": ["supplier", "vendor"],
    "customer": ["customer", "client", "account"],
    "plant": ["plant", "facility", "site"],
    "product": ["product", "item", "sku"],
    "employee": ["employee", "worker", "staff"],
    "department": ["department", "division"],
}


class CandidateEvaluation:
    def __init__(
        self,
        *,
        plan: MultiEntityPlan | None,
        score: float = 0.0,
        rejected_reasons: list[str] | None = None,
        source_count: int = 0,
    ) -> None:
        self.plan = plan
        self.score = score
        self.rejected_reasons = rejected_reasons or []
        self.source_count = source_count


def _norm(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum())


def _contains_keyword(name: str, keywords: list[str]) -> bool:
    n = _norm(name)
    return any(kw in n for kw in keywords)


def _infer_entity_type(question: str, tables: list[Any]) -> str:
    q = (question or "").lower()
    for entity_type, keywords in _ENTITY_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in q:
                return entity_type
    # Fallback: look for a common keyword across table columns.
    for entity_type, keywords in _ENTITY_TYPE_KEYWORDS.items():
        for t in tables:
            for col, _ty in t.columns:
                if _contains_keyword(col, keywords):
                    return entity_type
    return "entity"


def _entity_id_column(table: Any, entity_type: str) -> str | None:
    """Find a column that looks like the entity identity key."""
    entity_kws = _ENTITY_TYPE_KEYWORDS.get(entity_type, [entity_type])
    candidates = []
    for col, _ty in table.columns:
        n = _norm(col)
        if "id" in n or "code" in n or "number" in n or "key" in n or "sku" in n:
            if _contains_keyword(col, entity_kws):
                candidates.append(col)
    if candidates:
        return candidates[0]
    # Generic key column in table.
    for col, _ty in table.columns:
        n = _norm(col)
        if n.endswith("id") and n != "id":
            return col
    # Fallback: a name-style column for this entity is an acceptable natural key.
    return _entity_name_column(table, entity_type)


def _entity_name_column(table: Any, entity_type: str) -> str | None:
    """Find a column that looks like the entity display name."""
    entity_kws = _ENTITY_TYPE_KEYWORDS.get(entity_type, [entity_type])
    for col, _ty in table.columns:
        n = _norm(col)
        if "name" in n and _contains_keyword(col, entity_kws):
            return col
    # Generic name column.
    for col, _ty in table.columns:
        n = _norm(col)
        if n.endswith("name"):
            return col
    return None


def _measure_columns(table: Any, exclude: set[str]) -> list[str]:
    return [
        col for col, _ty in table.columns
        if col not in exclude and _contains_keyword(col, _MEASURE_KEYWORDS)
    ]


def _period_column(table: Any, exclude: set[str]) -> str | None:
    for col, _ty in table.columns:
        if col in exclude:
            continue
        if _contains_keyword(col, _PERIOD_KEYWORDS):
            return col
    return None


def _build_table_lookup(tables: list[Any]) -> dict[str, Any]:
    return {t.view_name: t for t in tables}


def _relationship_between(
    left: str, right: str, relationship_hints: list[dict[str, Any]]
) -> dict[str, Any] | None:
    pair = frozenset({left, right})
    for hint in relationship_hints or []:
        if frozenset({hint.get("left_table"), hint.get("right_table")}) == pair:
            return hint
    return None


def _join_key_for(
    hint: dict[str, Any], left: str, right: str
) -> tuple[list[str], list[str]]:
    """Return (left_key_columns, right_key_columns) from a relationship hint."""
    pairs = hint.get("join_key_pairs") or []
    left_keys = []
    right_keys = []
    for p in pairs:
        if p.get("is_period"):
            continue
        if hint["left_table"] == left:
            left_keys.append(p["left"])
            right_keys.append(p["right"])
        else:
            left_keys.append(p["right"])
            right_keys.append(p["left"])
    if not left_keys:
        # Fallback to single key columns in the hint itself.
        if hint["left_table"] == left:
            left_keys = [hint.get("left_join_key")]
            right_keys = [hint.get("right_join_key")]
        else:
            left_keys = [hint.get("right_join_key")]
            right_keys = [hint.get("left_join_key")]
    return left_keys, right_keys


def _find_path(
    tables: list[str],
    relationship_hints: list[dict[str, Any]],
) -> list[tuple[str, str, dict[str, Any]]] | None:
    """Find an ordered join path connecting the given tables."""
    if len(tables) == 1:
        return []
    path: list[tuple[str, str, dict[str, Any]]] = []
    for left, right in pairwise(tables):
        hint = _relationship_between(left, right, relationship_hints)
        if not hint:
            return None
        path.append((left, right, hint))
    return path


def _rank_combinations(
    tables: list[Any],
    relationship_hints: list[dict[str, Any]],
    entity_type: str,
    entity_names: list[str],
    intent: str,
    max_sources: int = 3,
) -> list[CandidateEvaluation]:
    """Generate and score candidate source combinations."""
    by_view = _build_table_lookup(tables)
    candidates: list[CandidateEvaluation] = []

    # Enumerate subsets from 1 to max_sources, preferring larger subsets.
    for size in range(min(max_sources, len(tables)), 0, -1):
        for combo in combinations([t.view_name for t in tables], size):
            plan, score, reasons = _evaluate_combination(
                combo,
                by_view,
                relationship_hints,
                entity_type,
                entity_names,
                intent,
                preferred_size=max_sources,
            )
            if plan:
                candidates.append(CandidateEvaluation(
                    plan=plan,
                    score=score,
                    source_count=size,
                ))
            else:
                candidates.append(CandidateEvaluation(
                    plan=None,
                    score=0.0,
                    rejected_reasons=reasons,
                    source_count=size,
                ))

    # Stable sort: higher score first; for ties prefer more sources.
    candidates.sort(key=lambda c: (c.score, c.source_count), reverse=True)
    return candidates


def _evaluate_combination(
    combo: tuple[str, ...],
    by_view: dict[str, Any],
    relationship_hints: list[dict[str, Any]],
    entity_type: str,
    entity_names: list[str],
    intent: str,
    preferred_size: int,
) -> tuple[MultiEntityPlan | None, float, list[str]]:
    """Score a table combination. Returns (plan, score, rejection_reasons)."""
    rejections: list[str] = []
    source_objs: list[SourceSpec] = []
    measures: list[MeasureSpec] = []
    relationships: list[RelationshipSpec] = []

    # Determine the canonical entity id/name columns from the first table that has them.
    entity_id_col: str | None = None
    entity_name_col: str | None = None
    for view_name in combo:
        t = by_view[view_name]
        if entity_id_col is None:
            entity_id_col = _entity_id_column(t, entity_type)
        if entity_name_col is None:
            entity_name_col = _entity_name_column(t, entity_type)
        if entity_id_col and entity_name_col:
            break

    if not entity_id_col:
        rejections.append(f"No entity id column found in {combo}")
        return None, 0.0, rejections

    # Every source must expose the entity id at the declared grain.
    period_col: str | None = None
    for view_name in combo:
        t = by_view[view_name]
        if entity_id_col not in [c for c, _ty in t.columns]:
            rejections.append(f"Table {view_name} missing entity id {entity_id_col}")
            return None, 0.0, rejections
        pc = _period_column(t, exclude={entity_id_col, entity_name_col or ""})
        if pc and period_col is None:
            period_col = pc
        # Build source spec and measures.
        excluded = {entity_id_col}
        if entity_name_col:
            excluded.add(entity_name_col)
        if pc:
            excluded.add(pc)
        msrs = _measure_columns(t, exclude=excluded)
        if not msrs:
            rejections.append(f"Table {view_name} has no recognizable measure")
            return None, 0.0, rejections
        source_measures = [
            MeasureSpec(
                name=col,
                column=col,
                table=view_name,
                aggregation="sum",
            )
            for col in msrs[:3]
        ]
        measures.extend(source_measures)
        grain = [entity_id_col]
        if pc:
            grain.append(pc)
        source_objs.append(SourceSpec(
            table=view_name,
            alias=_alias_for(view_name),
            grain=grain,
            measures=[m.name for m in source_measures],
            columns=[c for c, _ty in t.columns],
        ))

    # Validate join path across the combination (in the order given).
    path = _find_path(list(combo), relationship_hints)
    if len(combo) > 1 and path is None:
        rejections.append(f"No relationship path for {combo}")
        return None, 0.0, rejections

    if path:
        for left, right, hint in path:
            left_keys, right_keys = _join_key_for(hint, left, right)
            relationships.append(RelationshipSpec(
                left_table=left,
                right_table=right,
                left_key=left_keys,
                right_key=right_keys,
                declared_cardinality=hint.get("relationship_type", "one_to_many"),
            ))

    score = float(len(combo))
    if path:
        avg_conf = sum(float(h.get("join_confidence", 0.0)) for _l, _r, h in path) / len(path)
        score += avg_conf
    if period_col:
        score += 0.5
    if entity_name_col:
        score += 0.25
    if len(combo) < 2:
        score -= 1.0  # penalize single-source unless it is the only option

    selection_mode = "explicit" if len(entity_names) >= 2 else "top_n"
    requested = entity_names if len(entity_names) >= 2 else []
    question = (
        f"Compare {', '.join(requested)} using {', '.join(combo)}"
        if requested
        else f"Compare top {entity_type} entities across {', '.join(combo)}"
    )
    plan = MultiEntityPlan(
        analysis_id=f"multi_entity_{'_'.join(combo)}",
        intent=intent,
        title=f"{entity_type.title()} comparison across {', '.join(combo)}",
        business_question=question,
        source_strategy=SourceStrategy(
            preference="multi_source_first",
            minimum_preferred_sources=2,
            allow_single_source_fallback=True,
            selected_source_count=len(combo),
            fallback_used=len(combo) < 2,
            fallback_reason_code=None if len(combo) >= 2 else "no_multi_source_candidate",
            fallback_reason=None if len(combo) >= 2 else "No safe multi-source candidate survived validation",
            candidates_evaluated=1,
        ),
        entity=EntitySpec(
            type=entity_type,
            id_column=entity_id_col,
            name_column=entity_name_col or entity_id_col,
            selection_mode=selection_mode,
            requested_names=requested,
            maximum_entities=3,
        ),
        sources=source_objs,
        relationships=relationships,
        time=TimeSpec(
            period_column=period_col,
            period_grain="month",
        ),
        final_grain=[entity_id_col] + ([period_col] if period_col else []),
        measures=measures,
        method_bundle=_method_bundle_for_intent(intent),
    )
    return plan, score, rejections


def _alias_for(view_name: str) -> str:
    """Short SQL alias from view name."""
    parts = [p for p in view_name.replace("_", " ").split() if p]
    if parts:
        return parts[0][:3].lower()
    return "t"


def _method_bundle_for_intent(intent: str) -> Any:
    from app.services.multi_entity_insights.contract import MethodBundle, MethodRef
    primary = MethodRef(method_id="compare_multiple_groups", intent="compare_multiple_groups", role="primary")
    supporting: list[MethodRef] = []
    if intent in {"compare_entity_trends", "entity_contribution_to_change"}:
        supporting.append(MethodRef(method_id="detect_trend", intent="detect_trend"))
    if intent == "entity_contribution_to_change":
        supporting.append(MethodRef(method_id="contribution_to_change", intent="contribution_to_change"))
    return MethodBundle(primary=primary, supporting=supporting)


def select_candidates(
    question: str,
    tables: list[Any],
    relationship_hints: list[dict[str, Any]],
    *,
    max_sources: int = 3,
) -> list[CandidateEvaluation]:
    """Return multi-source-first ranked candidate evaluations."""
    intent, entity_names = infer_multi_entity_intent(question)
    if not intent or len(entity_names) < 2:
        intent = intent or "compare_entities"
        # Still allow candidate discovery if the user did not name entities;
        # the validator will reject them later if unresolved.
        entity_names = entity_names or []
    entity_type = _infer_entity_type(question, tables)
    return _rank_combinations(
        tables,
        relationship_hints,
        entity_type,
        entity_names,
        intent,
        max_sources=max_sources,
    )
