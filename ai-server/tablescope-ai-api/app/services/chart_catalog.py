"""Chart-family vocabulary parsed from the chart-selection best-practices markdown.

``app/prompts/chart_selection_best_practices.md`` (mirrored from platform-api,
the canonical copy) is the single source of truth for which chart families the
intelligence planner may propose. The planner prompt's chart vocabulary and the
plan-validation allowlist are both derived here — never hard-code chart-type
enums in prompt strings or validation sets.

The platform's visualization engine deterministically validates and re-ranks
every proposed chart against the actual data shape, so this module only needs
the vocabulary (families + subtypes) and a compact per-family usage digest for
the prompt; shape rules are enforced platform-side from the same markdown.
"""

from __future__ import annotations

import re
from functools import lru_cache

from app.services.prompt_loader import load_prompt_reference

CHART_CATALOG_PROMPT = "chart_selection_best_practices.md"

# Legacy planner aliases that predate the catalog and must stay accepted; the
# platform maps them onto real families (kpi_grid -> kpi, bullet -> gauge, ...).
_LEGACY_PLAN_TYPES = frozenset({"kpi_grid", "dual_line", "bullet", "sparkline_table", "none"})

_SECTION_RE = re.compile(
    r"^##\s+(?P<heading>[a-z0-9_]+)\s*$"
    r"(?P<body>.*?)"
    r"(?=^##\s+[a-z0-9_]+\s*$|\Z)",
    re.MULTILINE | re.DOTALL,
)
_RULES_RE = re.compile(r"```rules\s*\n(?P<rules>.*?)```", re.DOTALL)


def _field(rules_text: str, key: str) -> str:
    for line in rules_text.splitlines():
        line = line.strip()
        if line.lower().startswith(f"{key}:"):
            return line.partition(":")[2].strip()
    return ""


@lru_cache(maxsize=1)
def _parse() -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    """Return ({family: subtypes}, {family: first guidance sentence})."""
    text = load_prompt_reference(CHART_CATALOG_PROMPT)
    families: dict[str, tuple[str, ...]] = {}
    digests: dict[str, str] = {}
    if not text:
        return families, digests
    for m in _SECTION_RE.finditer(text):
        heading = m.group("heading")
        body = m.group("body")
        rules = _RULES_RE.search(body)
        if not rules:
            continue
        subtypes = tuple(
            s.strip()
            for s in _field(rules.group("rules"), "subtypes").split(",")
            if s.strip()
        )
        families[heading] = subtypes
        prose = _RULES_RE.sub("", body).strip()
        first_sentence = prose.split(".")[0].strip().replace("\n", " ")
        digests[heading] = first_sentence
    return families, digests


def allowed_plan_chart_types() -> frozenset[str]:
    """Every markdown family + subtype, plus legacy planner aliases."""
    families, _ = _parse()
    allowed: set[str] = set(_LEGACY_PLAN_TYPES)
    for family, subtypes in families.items():
        allowed.add(family)
        allowed.update(subtypes)
    # Fail open to the historical set if the markdown is missing so planning
    # never breaks on a bad deploy.
    if not families:
        allowed.update(
            {
                "line", "area", "scatter", "bubble", "bar", "horizontal_bar",
                "stacked_bar", "waterfall", "donut", "pie", "treemap", "funnel",
                "radar", "heatmap", "gauge",
            }
        )
    return frozenset(allowed)


def plan_chart_type_enum() -> str:
    """Pipe-joined vocabulary for the plan prompt's JSON schema line."""
    return "|".join(sorted(allowed_plan_chart_types()))


def planner_chart_digest() -> str:
    """Compact one-line-per-family usage guide injected into the plan prompt.

    Kept short deliberately: local models run with bounded num_ctx, so the full
    best-practices prose stays out of the plan prompt.
    """
    families, digests = _parse()
    if not families:
        return ""
    lines = ["Chart usage guide (pick the family whose shape matches the SQL you write):"]
    for family in families:
        digest = digests.get(family, "")
        if digest:
            lines.append(f"- {family}: {digest}.")
    return "\n".join(lines)
