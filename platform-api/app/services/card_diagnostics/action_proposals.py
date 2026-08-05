
from __future__ import annotations

from typing import Any

from .diagnostics_planning import OPPORTUNITY, RISK, ActionProposal, _humanize, _infer_metric, card_family

# ── Proposing what to do ─────────────────────────────────────────────────────


def propose_actions(
    card: dict[str, Any], findings: dict[str, Any] | None = None, *, max_actions: int = 3
) -> list[ActionProposal]:
    """Turn diagnostics into proposed next steps.

    Proposals are grounded in what was actually measured — a concentrated
    segment, a dated shift, a projected trajectory. When nothing specific was
    found the proposal is to investigate or monitor, which is honest, rather
    than inventing a confident recommendation.
    """
    family = card_family(card)
    if family is None:
        return []
    facts = findings or {}
    subject = _infer_metric(card) or "this metric"
    proposals: list[ActionProposal] = []

    segment = facts.get("top_segment")
    if segment:
        share = facts.get("top_segment_share")
        share_text = f" (~{share:.0%} of the movement)" if isinstance(share, int | float) else ""
        proposals.append(
            ActionProposal(
                headline=(
                    f"Target {segment} first"
                    if family != OPPORTUNITY
                    else f"Scale what {segment} is doing"
                ),
                rationale=(
                    f"{segment} concentrates the {subject} finding{share_text}, so a "
                    "focused intervention there moves the aggregate fastest."
                ),
                kind="mitigate" if family != OPPORTUNITY else "capture",
                confidence="high",
            )
        )

    when = facts.get("change_point_period")
    if when:
        proposals.append(
            ActionProposal(
                headline=f"Review what changed around {when}",
                rationale=(
                    f"{subject} shifted to a new level at {when}; identifying the "
                    "process, supplier or policy change at that point isolates the cause."
                ),
                kind="investigate",
                confidence="high",
            )
        )

    driver = facts.get("top_driver")
    if driver:
        proposals.append(
            ActionProposal(
                headline=f"Address {_humanize(str(driver))}",
                rationale=(
                    f"{_humanize(str(driver))} accounts for a significant share of the "
                    f"variation in {subject}, making it the highest-leverage input to change."
                ),
                kind="mitigate" if family != OPPORTUNITY else "capture",
                confidence="medium",
            )
        )

    projected = facts.get("forecast_direction")
    if projected in {"worsening", "declining", "increasing"} and family == RISK:
        proposals.append(
            ActionProposal(
                headline="Act before the trajectory compounds",
                rationale=(
                    f"{subject} is projected to keep {projected} if nothing changes, so "
                    "the cost of delay grows each period."
                ),
                kind="mitigate",
                confidence="medium",
            )
        )

    if not proposals:
        proposals.append(
            ActionProposal(
                headline=(
                    "Investigate before acting" if family == RISK else "Monitor for confirmation"
                ),
                rationale=(
                    "The diagnostics did not isolate a segment, a dated shift or a "
                    "driver, so there is no evidence yet to justify a targeted action."
                ),
                kind="investigate" if family == RISK else "monitor",
                confidence="low",
            )
        )
    return proposals[:max_actions]


# ── Questions the user can ask about the card ────────────────────────────────


def suggested_followups(
    card: dict[str, Any], *, dimensions: list[str] | None = None, max_items: int = 5
) -> list[str]:
    """Concrete next questions for the card's ask box.

    Phrased as things a user would actually type, and scoped to this card so the
    conversation continues the finding instead of starting a new topic.
    """
    family = card_family(card)
    if family is None:
        return []
    subject = _infer_metric(card) or "this"
    dims = dimensions or []
    # Ordered by purpose, not by convenience: the question that leads to an
    # action comes before generic drill-downs, because a truncated list must
    # still offer the useful one.
    items = [f"Why is {subject} moving?"]
    if family == RISK:
        items.append("What would reduce this risk?")
    elif family == OPPORTUNITY:
        items.append("How large is this opportunity?")
    else:
        items.append(f"Where is {subject} heading?")
    if dims:
        items.append(f"Break {subject} down by {_humanize(dims[0])}")
    items.append(f"What is driving {subject}?")
    items.append("Which documents mention this?")
    items.append(f"When did {subject} start changing?")
    if len(dims) > 1:
        items.append(f"Compare {_humanize(dims[0])} against {_humanize(dims[1])}")
    return items[:max_items]
