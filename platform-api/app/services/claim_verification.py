"""Test the causal claims an insight's narrative makes.

An insight card does not stop at what it measured. It writes sentences like
"gross margin declined, **indicating rising material costs**" — an assertion
about a *different* measure, in a *different* table, that nothing ever checked.
The number in the card is evidence; the clause after "indicating" is a
hypothesis, and presenting the two in the same paragraph makes the hypothesis
look equally established.

This module pulls those clauses out, finds the measure each one names, and puts
it to the same governed statistical test the rest of the analysis uses. The
outcome is one of three honest verdicts:

- **supported** — the named measure moved the way the claim says, with the
  magnitude quoted so "rising" becomes "rose 18.4% over the same window";
- **contradicted** — it moved the other way, which is the most valuable result
  here: the card's own narrative is wrong and would have been acted on;
- **untestable** — no measure in the project plausibly matches the claim, said
  plainly rather than quietly dropped.

Nothing here interprets; it checks. A claim that survives is still correlation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: Verdicts a checked claim can carry.
SUPPORTED = "supported"
CONTRADICTED = "contradicted"
INCONCLUSIVE = "inconclusive"
UNTESTABLE = "untestable"

#: Clauses that introduce an asserted cause or consequence. The card's own
#: hedging vocabulary — these are exactly the words that turn a measurement into
#: a story, which is why they mark the parts that need checking.
_CLAIM_PATTERNS = (
    r"indicat(?:ing|es|e)\s+(?P<claim>[^.,;]+)",
    r"suggest(?:ing|s)?\s+(?:that\s+)?(?P<claim>[^.,;]+)",
    r"driven\s+by\s+(?P<claim>[^.,;]+)",
    r"due\s+to\s+(?P<claim>[^.,;]+)",
    r"because\s+of\s+(?P<claim>[^.,;]+)",
    r"reflect(?:ing|s)\s+(?P<claim>[^.,;]+)",
    r"attributable\s+to\s+(?P<claim>[^.,;]+)",
    r"result(?:ing)?\s+from\s+(?P<claim>[^.,;]+)",
)

_RISING = re.compile(
    r"(?i)\b(rising|rise|rises|increas\w*|higher|growth|growing|grew|climb\w*|"
    r"escalat\w*|up|upward|surg\w*)\b"
)
_FALLING = re.compile(
    r"(?i)\b(falling|fall\w*|declin\w*|decreas\w*|lower|shrink\w*|drop\w*|"
    r"down|downward|erod\w*|contract\w*)\b"
)

#: Words that carry no signal when matching a claim to a column.
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "the", "of", "in", "on", "to", "for", "with", "from",
        "potential", "possible", "likely", "ongoing", "continued", "further",
        "issues", "issue", "problems", "problem", "concerns", "concern",
        "rising", "rise", "falling", "fall", "increasing", "increase",
        "decreasing", "decrease", "declining", "decline", "higher", "lower",
        "growth", "growing", "or", "other", "some", "significant", "material",
    }
)

#: Hedges. "rising X and potential Y issues" asserts a direction for X only —
#: distributing it onto the hedged conjunct would invent a claim the card never
#: made, and could then report it "contradicted".
_HEDGES = re.compile(r"(?i)\b(potential|possible|possibly|likely|may|might|risk of)\b")

#: `material` is a stopword above because "material change" is analyst filler —
#: but "material costs" names a real thing. Keep it when it qualifies a noun.
_KEEP_IF_QUALIFYING = {"material"}

#: Units and generic suffixes carried by column names. `MaterialCostUSD` is the
#: same measure as `MaterialCost`; counting `usd` against the match would dilute
#: a good column below the threshold and leave a real claim untested.
_UNIT_TOKENS = frozenset(
    {
        "usd", "eur", "gbp", "cad", "aud", "jpy", "pct", "percent", "amt",
        "amount", "total", "value", "val", "qty", "quantity", "num", "count",
        "avg", "average", "sum", "monthly", "weekly", "daily", "col", "id",
    }
)


@dataclass(frozen=True)
class Claim:
    """An assertion the card's narrative makes about some measure."""

    #: The clause as written, for quoting back to the reader.
    text: str
    #: Content words used to find the measure this claim is about.
    terms: tuple[str, ...]
    #: "up" | "down" | "" — the direction the claim asserts.
    direction: str = ""


@dataclass
class ClaimCheck:
    """The outcome of putting one claim to a statistical test."""

    claim: Claim
    verdict: str
    #: Business-language result, with magnitude when there is one.
    finding: str
    #: The column that was tested, when one was found.
    measure: str | None = None
    table: str | None = None
    envelope: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim.text,
            "verdict": self.verdict,
            "finding": self.finding,
            "measure": self.measure,
            "table": self.table,
        }


def _tokens(text: str) -> list[str]:
    """Content words, with camelCase and snake_case split apart."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(text))
    words = re.split(r"[^A-Za-z0-9]+", spaced.lower())
    return [w for w in words if w]


def _content_terms(text: str) -> tuple[str, ...]:
    """Words worth matching on, singularised so `costs` matches `cost`."""
    out: list[str] = []
    for word in _tokens(text):
        if len(word) < 3:
            continue
        if word in _STOPWORDS and word not in _KEEP_IF_QUALIFYING:
            continue
        # Crude singularisation: enough for column matching, and it keeps
        # `costs`/`cost` and `rates`/`rate` from being treated as unrelated.
        if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.append(word)
    return tuple(dict.fromkeys(out))


def extract_claims(card: dict[str, Any], *, max_claims: int = 3) -> list[Claim]:
    """Assertions in the card's prose that name something not yet measured.

    Only the narrative fields are read. A claim needs at least one content term
    to be checkable — "indicating problems" names nothing and is dropped rather
    than matched against an arbitrary column.
    """
    text = " ".join(
        str(card.get(k) or "")
        for k in ("summary", "title")
    )
    callout = card.get("callout")
    if isinstance(callout, dict):
        text += " " + str(callout.get("text") or "")
    if not text.strip():
        return []

    claims: list[Claim] = []
    seen: set[tuple[str, ...]] = set()
    for pattern in _CLAIM_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            clause = (match.group("claim") or "").strip()
            if not clause:
                continue
            clause_direction = ""
            if _RISING.search(clause):
                clause_direction = "up"
            elif _FALLING.search(clause):
                clause_direction = "down"

            # "rising material costs and potential profitability issues" is two
            # assertions about two different measures. Checking them as one
            # blurs the terms of both and matches neither.
            for part in _split_conjuncts(clause):
                terms = _content_terms(part)
                if not terms or terms in seen:
                    continue
                direction = ""
                if _RISING.search(part):
                    direction = "up"
                elif _FALLING.search(part):
                    direction = "down"
                seen.add(terms)
                claims.append(
                    Claim(
                        text=part,
                        terms=terms,
                        # A shared verb distributes ("rising X and Y"), but not
                        # onto a hedged conjunct, which asserts no direction.
                        direction=direction
                        or ("" if _HEDGES.search(part) else clause_direction),
                    )
                )
                if len(claims) >= max_claims:
                    return claims
    return claims


def _split_conjuncts(clause: str) -> list[str]:
    """Split a coordinated clause into its separate assertions."""
    parts = [p.strip() for p in re.split(r"\s+(?:and|as well as|plus)\s+", clause)]
    return [p for p in parts if p] or [clause.strip()]


def match_measure(
    claim: Claim,
    candidates: list[tuple[str, str]],
    *,
    min_score: float = 0.5,
) -> tuple[str, str] | None:
    """The (table, column) a claim is about, or ``None`` if nothing fits.

    ``candidates`` is ``[(table, column), ...]``. Matching is deliberately
    conservative: testing the wrong column would produce a confident verdict
    about something the claim never mentioned, which is worse than reporting
    that the claim could not be checked.
    """
    best: tuple[str, str] | None = None
    best_score = 0.0
    for table, column in candidates:
        column_terms = set(_content_terms(column)) - _UNIT_TOKENS
        if not column_terms:
            continue
        overlap = column_terms & set(claim.terms)
        if not overlap:
            continue
        # Proportion of the claim's terms the column accounts for, credited for
        # being a tight match rather than a long name that happens to contain
        # the word.
        score = len(overlap) / len(claim.terms)
        score *= len(overlap) / len(column_terms)
        if score > best_score:
            best_score, best = score, (table, column)
    return best if best_score >= min_score else None


def _direction_of(envelope: dict[str, Any]) -> tuple[str, float | None, float | None]:
    """(direction, slope, p_value) read from a trend envelope."""
    results = (envelope or {}).get("results")
    if not isinstance(results, dict):
        return "", None, None
    lowered = {str(k).lower(): v for k, v in results.items()}

    def _num(*keys: str) -> float | None:
        for key in keys:
            value = lowered.get(key)
            if isinstance(value, int | float) and not isinstance(value, bool):
                return float(value)
        return None

    slope = _num("slope", "sens_slope", "estimate", "trend")
    p = _num("p_value", "pvalue", "p")
    if slope is None or slope == 0:
        return "", slope, p
    return ("up" if slope > 0 else "down"), slope, p


def check_claim(
    claim: Claim,
    *,
    measure: str | None,
    table: str | None,
    envelope: dict[str, Any] | None,
    change_percent: float | None = None,
    period_label: str = "the same period",
    significance: float = 0.05,
) -> ClaimCheck:
    """Put one claim's direction to the test and say plainly what happened."""
    if not measure or not table:
        return ClaimCheck(
            claim=claim,
            verdict=UNTESTABLE,
            finding=(
                f"No measure in this project matches “{claim.text}”, so the "
                "claim could not be checked against data."
            ),
        )

    direction, slope, p = _direction_of(envelope or {})
    label = _humanize(measure)

    if not direction:
        return ClaimCheck(
            claim=claim, verdict=INCONCLUSIVE, measure=measure, table=table,
            envelope=envelope or {},
            finding=(
                f"{label} shows no clear movement over {period_label}, so "
                f"“{claim.text}” is neither supported nor contradicted."
            ),
        )

    if p is not None and p > significance:
        return ClaimCheck(
            claim=claim, verdict=INCONCLUSIVE, measure=measure, table=table,
            envelope=envelope or {},
            finding=(
                f"{label} moved {_word(direction)} over {period_label}, but not "
                f"significantly (p={p:.3f}) — too weak to confirm "
                f"“{claim.text}”."
            ),
        )

    magnitude = ""
    if change_percent is not None:
        magnitude = f" by {abs(change_percent):.1f}%"
    elif slope is not None:
        magnitude = f" ({slope:+,.4g} per period)"

    # A claim with no stated direction is informational only: the measure exists
    # and moved, but the card never said which way, so there is nothing to
    # contradict.
    if not claim.direction:
        return ClaimCheck(
            claim=claim, verdict=SUPPORTED, measure=measure, table=table,
            envelope=envelope or {},
            finding=(
                f"{label} moved {_word(direction)}{magnitude} over "
                f"{period_label}."
            ),
        )

    if direction == claim.direction:
        return ClaimCheck(
            claim=claim, verdict=SUPPORTED, measure=measure, table=table,
            envelope=envelope or {},
            finding=(
                f"Confirmed: {label} {_past(direction)}{magnitude} over "
                f"{period_label}"
                + (f" (p={p:.3f})." if p is not None else ".")
            ),
        )

    return ClaimCheck(
        claim=claim, verdict=CONTRADICTED, measure=measure, table=table,
        envelope=envelope or {},
        finding=(
            f"Not supported: the card says “{claim.text}”, but {label} actually "
            f"{_past(direction)}{magnitude} over {period_label}"
            + (f" (p={p:.3f})." if p is not None else ".")
        ),
    )


def _word(direction: str) -> str:
    return "up" if direction == "up" else "down"


def _past(direction: str) -> str:
    return "rose" if direction == "up" else "fell"


def _humanize(name: str) -> str:
    """`material_cost_usd` / `MaterialCostUSD` -> `Material Cost USD`."""
    return " ".join(w.capitalize() if not w.isupper() else w for w in _tokens(name)) or name


def percent_change(rows: list[dict[str, Any]], measure: str) -> float | None:
    """Change from the first to the last period, as a percentage.

    This is what turns "rising" into "rose 18.4%" — the magnitude the reader
    needs to judge whether the claim matters, not just whether it holds.
    """
    values: list[float] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        value = row.get(measure)
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        values.append(float(value))
    if len(values) < 2:
        return None
    first, last = values[0], values[-1]
    if first == 0:
        return None
    return (last - first) / abs(first) * 100.0
