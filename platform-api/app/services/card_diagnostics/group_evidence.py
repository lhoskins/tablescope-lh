
from __future__ import annotations

from typing import Any, cast

#: Intents whose method needs raw rows but whose *chart* needs per-group totals.
GROUP_EVIDENCE_INTENTS = frozenset({"compare_multiple_groups", "compare_two_groups"})


def summarise_group_evidence(
    rows: list[dict[str, Any]],
    group_key: str,
    value_key: str,
    *,
    max_groups: int = 20,
) -> tuple[list[dict[str, Any]], list[str], int | None]:
    """Per-group averages for a group comparison, worst group first.

    A group comparison feeds *raw* rows to the method — Welch's ANOVA needs the
    within-group spread, not a pre-aggregated mean. Charting those same rows is
    what produced a wall of identical bars with the same work centre repeated
    down the axis: it was plotting individual records, not groups.

    The chart needs the opposite shape, so the rows are folded here into one
    entry per group, ranked by the measure. Ranking is what makes the chart
    answer "where is the problem" — the leading bar *is* the answer.

    Returns ``(rows, columns, marked_index)``; ``marked_index`` is the leading
    group, or ``None`` when the groups are too even for one to lead.
    """
    totals: dict[str, list[float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        group = row.get(group_key)
        value = row.get(value_key)
        if group is None:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                continue
        if not isinstance(value, int | float):
            continue
        totals.setdefault(str(group), []).append(float(value))

    if len(totals) < 2:
        return [], [], None

    summary: list[dict[str, Any]] = [
        {
            group_key: group,
            value_key: round(sum(values) / len(values), 4),
            "observations": len(values),
        }
        for group, values in totals.items()
    ]
    summary.sort(key=lambda r: abs(float(cast(Any, r[value_key]))), reverse=True)
    summary = summary[:max_groups]

    # Only claim a leader when one actually leads. Marking the top bar of an
    # essentially flat ranking would point at noise.
    marked: int | None = None
    if len(summary) >= 2:
        top = abs(float(cast(Any, summary[0][value_key])))
        runner_up = abs(float(cast(Any, summary[1][value_key])))
        if top > 0 and (top - runner_up) / top >= 0.10:
            marked = 0

    return summary, [group_key, value_key, "observations"], marked


def describe_group_leader(
    summary: list[dict[str, Any]],
    group_key: str,
    value_key: str,
    *,
    marked: int | None,
) -> str:
    """One sentence naming the segment the problem sits in.

    "Groups differ significantly (p=0.000)" is a true statement that tells a
    plant manager nothing — it reports that the test rejected its null
    hypothesis, not where to go. This names the leading group, its level, and
    how far clear of the next one it is, which is the part someone can act on.

    Returns ``""`` when no group leads clearly enough to name one.
    """
    if marked is None or not summary or marked >= len(summary):
        return ""
    lead = summary[marked]
    name = lead.get(group_key)
    value = lead.get(value_key)
    if name is None or not isinstance(value, int | float) or isinstance(value, bool):
        return ""

    sentence = f"{name} leads at {float(value):,.4g} per record"
    runner_up = summary[marked + 1] if marked + 1 < len(summary) else None
    if runner_up:
        other = runner_up.get(value_key)
        if isinstance(other, int | float) and not isinstance(other, bool) and other:
            gap = (abs(float(value)) - abs(float(other))) / abs(float(other))
            if gap > 0:
                sentence += f", {gap:.0%} above {runner_up.get(group_key)}"
    n = lead.get("observations")
    if isinstance(n, int):
        sentence += f" (across {n} observations)"
    return sentence + "."
