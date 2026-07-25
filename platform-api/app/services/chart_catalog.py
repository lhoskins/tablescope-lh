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
    excludes: frozenset[str] = frozenset()
    roles: dict[str, str] = field(default_factory=dict)
    subtypes: tuple[str, ...] = ()
    score: float = 0.5
    guidance: str = ""

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
        if self.excludes & shape.traits:
            return False
        return True


@dataclass(frozen=True)
class ShapeSummary:
    """Engine-computed summary of a result set's shape.

    ``traits`` carries the special markers the rules grammar understands:
    ``time``, ``raw``, ``flow``, ``hierarchy``, ``ohlc``, ``single_row``,
    ``rate``, ``geo``, ``period_only_dimension``, ``negative_values``.
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
        excludes=frozenset(_parse_csv(fields.get("excludes", ""))),
        roles=_parse_roles(fields.get("roles", "")),
        subtypes=_parse_csv(fields.get("subtypes", "")),
        # 0.0 is a meaningful "gated off" score — only None falls back.
        score=score if score is not None else 0.5,
        guidance=guidance.strip(),
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

    Zero-scored families (gated, e.g. ``map``) are excluded.
    """
    rules = [
        r
        for r in load_chart_catalog().values()
        if r.score > 0 and r.eligible(shape)
    ]
    return sorted(rules, key=lambda r: r.score, reverse=True)


def planner_guidance() -> str:
    """The full markdown text for inclusion in LLM planner prompts."""
    return load_prompt_reference(CHART_CATALOG_PROMPT)
