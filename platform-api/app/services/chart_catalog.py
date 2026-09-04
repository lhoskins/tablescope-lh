"""Machine-readable chart-family catalog parsed from the best-practices markdown.

``app/prompts/chart_selection_best_practices.md`` is the single source of truth
for chart selection: the LLM planner receives its prose, and the deterministic
visualization engine consumes the fenced ``rules`` blocks parsed here. Adding or
re-scoping a chart family is a markdown edit — application code must never
enumerate family names.

The rules-block grammar is deliberately tiny (flat ``key: value`` lines) so no
YAML dependency is needed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.services.prompt_loader import load_prompt_reference

logger = logging.getLogger(__name__)

CHART_CATALOG_PROMPT = "chart_selection_best_practices.md"

_SECTION_RE = re.compile(
    r"^##\s+(?P<heading>[a-z0-9_]+)\s*$"
    r"(?P<body>.*?)"
    r"(?=^##\s+[a-z0-9_]+\s*$|\Z)",
    re.MULTILINE | re.DOTALL,
)
_RULES_RE = re.compile(r"```rules\s*\n(?P<rules>.*?)```", re.DOTALL)


@dataclass(frozen=True)
class ChartFamilyRule:
    """Eligibility and role contract for one chart family."""

    family: str
    min_dims: int = 0
    max_dims: int | None = None
    min_measures: int = 0
    max_measures: int | None = None
    needs: frozenset[str] = frozenset()
    needs_any: frozenset[str] = frozenset()
    excludes: frozenset[str] = frozenset()
    roles: dict[str, str] = field(default_factory=dict)
    subtypes: tuple[str, ...] = ()
    score: float = 0.5
    guidance: str = ""
    # Optional fit hints (from the markdown) used by fit_score(); a family with
    # no hints keeps its base score whenever eligible.
    min_rows: int = 0
    ideal_rows: tuple[int, int] | None = None
    ideal_dim_card: tuple[int, int] | None = None
    ideal_dim2_card: tuple[int, int] | None = None

    def eligible(self, shape: ShapeSummary) -> bool:
        """True when ``shape`` satisfies this family's requirements."""
        if shape.dims < self.min_dims:
            return False
        if self.max_dims is not None and shape.dims > self.max_dims:
            return False
        if shape.measures < self.min_measures:
            return False
        if self.max_measures is not None and shape.measures > self.max_measures:
            return False
        if not self.needs <= shape.traits:
            return False
        if self.needs_any and not (self.needs_any & shape.traits):
            return False
        if self.excludes & shape.traits:
            return False
        return True


@dataclass(frozen=True)
class ShapeSummary:
    """Engine-computed summary of a result set's shape.

    ``traits`` carries the special markers the rules grammar understands:
    ``time``, ``raw``, ``flow``, ``hierarchy``, ``ohlc``, ``single_row``,
    ``rate``, ``geo``, ``period_only_dimension``, ``negative_values``, ``stage``.
    """

    dims: int
    measures: int
    traits: frozenset[str] = frozenset()


def _parse_int(value: str) -> int | None:
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return None


def _parse_float(value: str) -> float | None:
    try:
        return float(value.strip())
    except (TypeError, ValueError):
        return None


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(t.strip() for t in value.split(",") if t.strip())


def _parse_range(value: str) -> tuple[int, int] | None:
    """Parse ``lo-hi`` (e.g. ``3-30``) into an inclusive int range."""
    if "-" not in value:
        return None
    lo_s, _, hi_s = value.partition("-")
    lo, hi = _parse_int(lo_s), _parse_int(hi_s)
    if lo is None or hi is None or lo > hi:
        return None
    return (lo, hi)


def _parse_roles(value: str) -> dict[str, str]:
    roles: dict[str, str] = {}
    for pair in _parse_csv(value):
        if "=" in pair:
            k, _, v = pair.partition("=")
            if k.strip() and v.strip():
                roles[k.strip()] = v.strip()
    return roles


def _parse_rules_block(family_heading: str, text: str, guidance: str) -> ChartFamilyRule | None:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip().lower()] = value.strip()

    family = fields.get("family") or family_heading
    if family != family_heading:
        logger.warning(
            "chart catalog: heading %r != family %r; using heading",
            family_heading,
            family,
        )
        family = family_heading

    min_dims = _parse_int(fields.get("min_dims", ""))
    min_measures = _parse_int(fields.get("min_measures", ""))
    score = _parse_float(fields.get("score", ""))
    return ChartFamilyRule(
        family=family,
        min_dims=min_dims if min_dims is not None else 0,
        max_dims=_parse_int(fields.get("max_dims", "")),
        min_measures=min_measures if min_measures is not None else 0,
        max_measures=_parse_int(fields.get("max_measures", "")),
        needs=frozenset(_parse_csv(fields.get("needs", ""))),
        needs_any=frozenset(_parse_csv(fields.get("needs_any", ""))),
        excludes=frozenset(_parse_csv(fields.get("excludes", ""))),
        roles=_parse_roles(fields.get("roles", "")),
        subtypes=_parse_csv(fields.get("subtypes", "")),
        # 0.0 is a meaningful "gated off" score — only None falls back.
        score=score if score is not None else 0.5,
        guidance=guidance.strip(),
        min_rows=_parse_int(fields.get("min_rows", "")) or 0,
        ideal_rows=_parse_range(fields.get("ideal_rows", "")),
        ideal_dim_card=_parse_range(fields.get("ideal_dim_card", "")),
        ideal_dim2_card=_parse_range(fields.get("ideal_dim2_card", "")),
    )


@lru_cache(maxsize=1)
def load_chart_catalog() -> dict[str, ChartFamilyRule]:
    """Parse the best-practices markdown into family rules, keyed by family id.

    Returns an empty dict when the file is missing (callers must fail open to
    their existing behavior rather than crash).
    """
    text = load_prompt_reference(CHART_CATALOG_PROMPT)
    if not text:
        logger.warning("chart catalog: %s missing or empty", CHART_CATALOG_PROMPT)
        return {}

    catalog: dict[str, ChartFamilyRule] = {}
    for m in _SECTION_RE.finditer(text):
        heading = m.group("heading")
        body = m.group("body")
        rules_match = _RULES_RE.search(body)
        if not rules_match:
            continue
        guidance = _RULES_RE.sub("", body)
        rule = _parse_rules_block(heading, rules_match.group("rules"), guidance)
        if rule is None:
            continue
        if rule.family in catalog:
            logger.warning("chart catalog: duplicate family %r ignored", rule.family)
            continue
        catalog[rule.family] = rule
    return catalog


def chart_families() -> tuple[str, ...]:
    """Every family id declared in the markdown, in file order."""
    return tuple(load_chart_catalog().keys())


def allowed_plan_chart_types() -> frozenset[str]:
    """Planner-facing allowed set: every declared family plus its subtypes.

    Replaces hard-coded ``_ALLOWED_PLAN_CHART_TYPES``-style enums.
    """
    allowed: set[str] = set()
    for rule in load_chart_catalog().values():
        allowed.add(rule.family)
        allowed.update(rule.subtypes)
    return frozenset(allowed)


def eligible_families(shape: ShapeSummary) -> list[ChartFamilyRule]:
    """Families whose rules the shape satisfies, best base-score first.

    Zero-scored families (gated, e.g. ``map``) are excluded. Prefer
    :func:`fit_ranked` when per-dataset facts (row count, cardinalities) are
    available — base score alone over-selects broadly-eligible families.
    """
    rules = [
        r
        for r in load_chart_catalog().values()
        if r.score > 0 and r.eligible(shape)
    ]
    return sorted(rules, key=lambda r: r.score, reverse=True)


@dataclass(frozen=True)
class ShapeFacts:
    """Per-dataset facts that turn base eligibility into a fit confidence.

    ``dim_cardinalities`` is ordered: primary dimension first. Missing facts
    (zero/empty) skip the corresponding fit checks rather than penalizing.
    """

    row_count: int = 0
    dim_cardinalities: tuple[int, ...] = ()


def _range_multiplier(value: int, ideal: tuple[int, int] | None) -> float:
    """Graded fit penalty for a value against a family's ideal range.

    1.0 inside the range; outside it the penalty scales with how far out the
    value is (a 400-category "heatmap" axis is far worse than a 35-category
    one), floored at 0.15 so a poor fit is demoted rather than erased.
    Unknown values (<= 0) or families without the hint are not penalized.
    """
    if ideal is None or value <= 0:
        return 1.0
    lo, hi = ideal
    if lo <= value <= hi:
        return 1.0
    ratio = (hi / value) if value > hi else (value / lo)
    return max(0.15, min(1.0, ratio))


def fit_score(rule: ChartFamilyRule, shape: ShapeSummary, facts: ShapeFacts) -> float:
    """Confidence that ``rule``'s family fits THIS dataset (0 = do not use).

    Deterministic: base score from the markdown, multiplied down when the
    dataset's row count / dimension cardinalities fall outside the family's
    declared ideal ranges. All tuning lives in the markdown fit hints.
    """
    if rule.score <= 0 or not rule.eligible(shape):
        return 0.0
    if rule.min_rows and 0 < facts.row_count < rule.min_rows:
        return 0.0
    confidence = rule.score
    # Specificity: a family that consumes the data's full structure explains it
    # better than one that discards a dimension/measure (a 2-dimension matrix is
    # a heatmap, not a bar chart that drops a dimension).
    if shape.dims and (
        rule.min_dims >= shape.dims or "category" in rule.needs_any
    ):
        confidence += 0.15
    if shape.measures >= 2 and rule.min_measures >= shape.measures:
        confidence += 0.05
    confidence *= _range_multiplier(facts.row_count, rule.ideal_rows)
    dim1 = facts.dim_cardinalities[0] if len(facts.dim_cardinalities) >= 1 else 0
    dim2 = facts.dim_cardinalities[1] if len(facts.dim_cardinalities) >= 2 else 0
    confidence *= _range_multiplier(dim1, rule.ideal_dim_card)
    confidence *= _range_multiplier(dim2, rule.ideal_dim2_card)
    return round(min(confidence, 1.0), 4)


def fit_ranked(
    shape: ShapeSummary, facts: ShapeFacts
) -> list[tuple[ChartFamilyRule, float]]:
    """Every family with a positive fit confidence for this dataset, best first.

    The intended selection contract: ``fit_ranked(...)[0]`` is the chart to
    display; the following entries feed the chart-suggestion list.
    """
    scored = [
        (rule, fit_score(rule, shape, facts))
        for rule in load_chart_catalog().values()
    ]
    ranked = [(r, s) for r, s in scored if s > 0]
    ranked.sort(key=lambda rs: rs[1], reverse=True)
    return ranked


def planner_guidance() -> str:
    """The full markdown text for inclusion in LLM planner prompts."""
    return load_prompt_reference(CHART_CATALOG_PROMPT)
