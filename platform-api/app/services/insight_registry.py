"""Retrievable registry of generated insight cards.

Asking "show me the query for *Material Costs vs Revenue Trend*" used to fail in
a specific, misleading way: the ask paths were given **knowledge-graph context
only** (documents, KPIs, tables), and no path could look a card up. With nothing
to retrieve, the model did the only thing it could — it *invented* a plausible
SQL query from the documents and presented it as the card's query.

Cards already store everything needed to answer truthfully: ``sql``, the
executed ``result``, the governed ``analyticalMethod`` envelope and their source
tables. This module makes them **retrievable**:

* :func:`resolve_insight_reference` finds the card a question refers to from a
  partial title — typing a distinctive fragment is enough, and an ambiguous
  fragment is reported as ambiguous rather than silently guessed.
* :func:`format_insight_context` renders the matched card as grounding text that
  states the stored SQL verbatim, with an explicit instruction never to invent
  one.
* :func:`insight_catalog_context` lists the available cards so the assistant
  knows what exists at all — the "what insights do we have?" question.

Pure and dependency-light: matching and formatting are unit-testable without a
database. Loading the cached cards stays with the caller.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: Phrasings that mean "the user is pointing at a named insight card".
_REFERENCE_RE = re.compile(
    r"(?i)\b(?:insight|card|business insight|project insight)\b[^:]{0,24}"
    r"(?:title|titled|named|called)?\s*[:\-]?\s*(?P<title>.{3,120})$"
)
_QUOTED_RE = re.compile(r"[\"“'']([^\"”'']{3,120})[\"”'']")
#: Words that carry no signal when matching a title fragment.
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "by",
        "with", "vs", "versus", "please", "show", "me", "display", "query",
        "sql", "insight", "card", "business", "project", "title", "titled",
        "what", "is", "was", "why", "how", "did", "that", "this", "it",
    }
)


@dataclass
class InsightRef:
    """A card the user's question refers to."""

    card: dict[str, Any]
    score: float
    title: str


@dataclass
class InsightMatch:
    """Outcome of resolving a question against the available cards."""

    match: InsightRef | None = None
    #: Populated when several cards match a fragment equally well; the caller
    #: should ask which one rather than answering about an arbitrary card.
    ambiguous: list[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.match is not None


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def extract_title_fragment(question: str) -> str:
    """The part of a question that names a card, if any.

    Handles the phrasings users actually type: ``Business Insight Title: X``,
    ``the "X" card``, ``show me the query for X``.
    """
    if not question:
        return ""
    quoted = _QUOTED_RE.search(question)
    if quoted:
        return quoted.group(1).strip()
    m = _REFERENCE_RE.search(question.strip())
    if m:
        return m.group("title").strip().rstrip("?.!")
    # "…query for <title>" / "…about <title>"
    tail = re.search(r"(?i)\b(?:for|about|on)\s+(?P<title>.{3,120})$", question.strip())
    if tail:
        return tail.group("title").strip().rstrip("?.!")
    return ""


def score_title(fragment: str, title: str) -> float:
    """How well a user's fragment identifies a card title (0..1).

    Substring containment wins outright so a distinctive fragment is enough;
    otherwise the score is the share of the fragment's meaningful words present
    in the title.
    """
    frag = str(fragment or "").strip().lower()
    full = str(title or "").strip().lower()
    if not frag or not full:
        return 0.0
    if frag == full:
        return 1.0
    if frag in full:
        return 0.9
    frag_tokens = _tokens(frag)
    if not frag_tokens:
        return 0.0
    overlap = frag_tokens & _tokens(full)
    # Scaled below the containment score: a contiguous fragment is a more
    # precise signal than the same words scattered through the title, and
    # unscaled full overlap would otherwise tie with an exact match.
    return 0.85 * (len(overlap) / len(frag_tokens))


def resolve_insight_reference(
    question: str,
    cards: list[dict[str, Any]],
    *,
    threshold: float = 0.6,
    ambiguity_margin: float = 0.08,
) -> InsightMatch:
    """Find the card a question refers to.

    A partial title is enough when it is distinctive. When two cards score
    within ``ambiguity_margin`` of each other the result is reported as
    **ambiguous** — answering about an arbitrary one of them would be worse than
    asking which was meant.
    """
    if not cards:
        return InsightMatch()

    fragment = extract_title_fragment(question) or question
    scored: list[tuple[float, dict[str, Any]]] = []
    for card in cards:
        title = str(card.get("title") or "")
        if not title:
            continue
        scored.append((score_title(fragment, title), card))
    if not scored:
        return InsightMatch()

    scored.sort(key=lambda s: s[0], reverse=True)
    best_score, best_card = scored[0]
    if best_score < threshold:
        return InsightMatch()

    rivals = [
        c for s, c in scored[1:]
        if s >= best_score - ambiguity_margin and s >= threshold
    ]
    if rivals:
        titles = [str(best_card.get("title"))] + [str(c.get("title")) for c in rivals]
        return InsightMatch(ambiguous=titles[:5])

    return InsightMatch(
        match=InsightRef(card=best_card, score=best_score, title=str(best_card.get("title")))
    )


def format_insight_context(ref: InsightRef) -> str:
    """Grounding text that lets the model answer *from the card*, not invent.

    The stored SQL is quoted verbatim and the model is told explicitly not to
    write a replacement — inventing a query that looks right is the exact
    failure this module exists to prevent.
    """
    card = ref.card
    lines: list[str] = [f'Insight card: "{ref.title}"']

    summary = card.get("summary")
    if summary:
        lines.append(f"Summary: {summary}")

    sources = card.get("sources") or {}
    tables = sources.get("tables") if isinstance(sources, dict) else None
    if tables:
        lines.append("Source tables: " + ", ".join(str(t) for t in tables[:8]))

    envelope = card.get("analyticalMethod") or card.get("method_envelope") or {}
    if isinstance(envelope, dict) and envelope.get("method"):
        engine = str(envelope.get("executionEngine") or "").lower()
        line = f"Analytical method: {envelope['method']}"
        if engine:
            line += f" (executed in {'R' if engine == 'r' else engine})"
        lines.append(line)
        n = envelope.get("usableN") or envelope.get("n")
        if n:
            lines.append(f"Observations used: {n}")

    sql = (card.get("sql") or "").strip()
    if sql:
        lines.append(
            "This is the EXACT SQL this insight was generated from. Quote it as "
            "the answer; do NOT write a different query:"
        )
        lines.append("```sql\n" + sql + "\n```")
    else:
        lines.append(
            "This insight has no stored SQL (it was not generated from a query). "
            "Say so plainly instead of inventing one."
        )

    result = card.get("result") or {}
    columns = result.get("columns") if isinstance(result, dict) else None
    rows = result.get("rows") if isinstance(result, dict) else None
    if columns:
        lines.append("Result columns: " + ", ".join(str(c) for c in columns[:12]))
    if isinstance(rows, list) and rows:
        lines.append(
            "Recorded values from this insight (use these to analyze further, "
            "spot trends, or answer follow-up questions — do not invent numbers "
            "not shown here):"
        )
        for row in rows[:10]:
            if isinstance(row, dict):
                lines.append(
                    "- " + ", ".join(f"{k}={v}" for k, v in row.items())
                )
            else:
                lines.append(f"- {row}")

    return "\n".join(lines)


def format_ambiguous(titles: list[str]) -> str:
    """Grounding text for an ambiguous reference — ask, do not guess."""
    listed = "\n".join(f"- {t}" for t in titles)
    return (
        "The question could refer to more than one insight card:\n"
        f"{listed}\n"
        "Ask the user which one they mean instead of answering about one of them."
    )


def insight_catalog_context(cards: list[dict[str, Any]], *, limit: int = 40) -> str:
    """A list of the insight cards that exist, so the assistant knows the menu.

    Without this, "what insights do we have?" is answered from documents rather
    than from what was actually generated.
    """
    titles: list[str] = []
    for card in cards:
        title = str(card.get("title") or "").strip()
        if not title:
            continue
        group = str(card.get("group") or card.get("insightType") or "").strip()
        titles.append(f"- {title}" + (f" [{group}]" if group else ""))
        if len(titles) >= limit:
            break
    if not titles:
        return ""
    return "Insight cards currently available:\n" + "\n".join(titles)

# ── Loading the cards a tenant actually has ──────────────────────────────────


#: Project Insight report sections that hold Business-Insight-style cards.
_PROJECT_INSIGHT_CARD_KEYS = ("risks", "trends", "opportunities", "analysis")


def _project_insight_result(card: dict[str, Any]) -> dict[str, Any] | None:
    """Reconstruct a ``{columns, rows}`` result from a Project Insight card's
    rendered chart, so cards that never stored a query result (e.g. narrative
    or graph-derived cards) still give the model real values to reason over.
    """
    chart = card.get("chart") or {}
    data = chart.get("data") if isinstance(chart, dict) else None
    series = data.get("series") if isinstance(data, dict) else None
    if not isinstance(series, list) or not series:
        return None
    label_col = str(card.get("labelColumn") or "label")
    value_col = str(card.get("valueColumn") or "value")
    if isinstance(series[0], dict):
        return {
            "columns": [label_col, value_col],
            "rows": [
                {label_col: s.get("label"), value_col: s.get("value")}
                for s in series
                if isinstance(s, dict)
            ],
        }
    return {
        "columns": [label_col, value_col],
        "rows": [
            {label_col: s[0], value_col: s[1]}
            for s in series
            if isinstance(s, list | tuple) and len(s) >= 2
        ],
    }


def _normalize_project_insight_card(card: dict[str, Any]) -> dict[str, Any]:
    """Adapt a Project Insight card to the shape ``format_insight_context``
    expects (nested ``sources.tables`` rather than a flat ``sourceTables``, and
    a ``result`` block reconstructed from the chart when none was stored).
    """
    normalized = dict(card)
    if not normalized.get("sources"):
        tables = card.get("sourceTables") or []
        if tables:
            normalized["sources"] = {"tables": tables}
    if not normalized.get("result"):
        result = _project_insight_result(card)
        if result:
            normalized["result"] = result
    return normalized


async def load_tenant_insight_cards(
    session: Any,
    *,
    tenant_id: int,
    project_id: int | None = None,
    user_id: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Every generated insight card visible to a tenant, newest first.

    Reads the shared Business-Insight cache rather than regenerating: the cards
    the user is looking at on screen are exactly the rows stored there, so a
    question about one resolves against what they can actually see. When asking
    about a single project, the caller's own Project Insight snapshot is also
    searched — those cards (risks/trends/opportunities/analysis) are generated
    by a separate on-demand run and never land in the shared Business Insight
    cache, so a card visible on the Project Insight page would otherwise be
    invisible to this lookup. Cards already in the Business Insight cache win on
    a title collision; the snapshot only supplements what isn't already there.

    Fail-open — a cache problem returns no cards, which degrades the assistant to
    its previous (non-card-aware) behaviour rather than breaking the answer.
    """
    try:
        from sqlalchemy import select

        from app.models.business_insight_result import BusinessInsightResult

        stmt = select(BusinessInsightResult).where(
            BusinessInsightResult.tenant_id == tenant_id
        )
        if project_id is not None:
            stmt = stmt.where(BusinessInsightResult.project_id == project_id)
        stmt = stmt.order_by(BusinessInsightResult.updated_at.desc())

        rows = (await session.scalars(stmt)).all()
        cards: list[dict[str, Any]] = []
        seen_titles: set[str] = set()
        for row in rows:
            payload = row.payload or {}
            insights = payload.get("insights")
            if not isinstance(insights, list):
                continue
            for card in insights:
                if isinstance(card, dict) and card.get("title"):
                    cards.append(card)
                    seen_titles.add(str(card["title"]).strip().lower())
                if len(cards) >= limit:
                    return cards

        if project_id is not None and user_id is not None:
            cards.extend(
                await load_project_insight_snapshot_cards(
                    session,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    project_id=project_id,
                    exclude_titles=seen_titles,
                    limit=limit - len(cards),
                )
            )
        return cards
    except Exception:
        logger.exception(
            "insight registry: could not load cards (tenant=%s project=%s)",
            tenant_id, project_id,
        )
        return []


async def load_project_insight_snapshot_cards(
    session: Any,
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    exclude_titles: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Cards from the caller's own Project Insight snapshot, newest first.

    One row per (tenant, user, project, suite); ``suite`` defaults to
    ``"project_insight"`` for the standard report.
    """
    if limit <= 0:
        return []
    from sqlalchemy import select

    from app.models.project_intelligence_snapshot import ProjectIntelligenceSnapshot

    snap = await session.scalar(
        select(ProjectIntelligenceSnapshot).where(
            ProjectIntelligenceSnapshot.tenant_id == tenant_id,
            ProjectIntelligenceSnapshot.user_id == user_id,
            ProjectIntelligenceSnapshot.project_id == project_id,
            ProjectIntelligenceSnapshot.suite == "project_insight",
        )
    )
    if snap is None:
        return []

    payload = snap.payload or {}
    cards: list[dict[str, Any]] = []
    for key in _PROJECT_INSIGHT_CARD_KEYS:
        section = payload.get(key)
        if not isinstance(section, list):
            continue
        for card in section:
            if not isinstance(card, dict) or not card.get("title"):
                continue
            title = str(card["title"]).strip().lower()
            if title in exclude_titles:
                continue
            exclude_titles.add(title)
            cards.append(_normalize_project_insight_card(card))
            if len(cards) >= limit:
                return cards
    return cards


def build_insight_context(question: str, cards: list[dict[str, Any]]) -> str:
    """Grounding text for a question, given the tenant's cards.

    Returns the matched card's stored SQL and provenance, an ambiguity prompt
    when a fragment matches several cards, or the catalog when the question is
    about insights generally. Empty string when no card is relevant, so ordinary
    questions are unaffected.
    """
    if not cards:
        return ""
    match = resolve_insight_reference(question, cards)
    if match.resolved and match.match is not None:
        return format_insight_context(match.match)
    if match.ambiguous:
        return format_ambiguous(match.ambiguous)
    if re.search(r"(?i)\b(insight|insights|card|cards)\b", question or ""):
        return insight_catalog_context(cards)
    return ""

#: "show me the query/SQL for X" — a retrieval request, not a generation request.
_QUERY_REQUEST_RE = re.compile(
    r"(?i)\b(?:show|display|see|view|get|what(?:'s| is)?|give)\b[^?]{0,40}"
    r"\b(?:query|sql|statement)\b"
)


def is_query_request(question: str) -> bool:
    """True when the user is asking to SEE a card's query, not to build one.

    This distinction matters: generating SQL for such a question is exactly how
    an invented query gets presented as the card's query. When this is true and a
    card resolves, answer from the stored SQL instead of calling the generator.
    """
    return bool(_QUERY_REQUEST_RE.search(question or ""))


def _result_from_chart(card: dict[str, Any]) -> dict[str, Any]:
    """Best-effort result grid from a card's rendered chart.

    Method-driven cards do not persist the raw ``result`` block, but the chart
    already contains the same points (label/value/value2) plus role names. This
    lets a stored-SQL answer still carry a small table the chat surface can
    render, without requiring the full result frame to be duplicated in the
    cache payload.
    """
    chart = card.get("chart") or {}
    data = chart.get("data") or {}
    if not isinstance(data, dict):
        return {}

    rows = data.get("rows")
    if rows and isinstance(rows, list):
        cols = data.get("columns") or (list(rows[0].keys()) if rows else [])
        return {"columns": cols, "rows": rows}

    series = data.get("series")
    if not series or not isinstance(series, list):
        return {}

    roles = chart.get("roles") or {}
    series_labels = chart.get("seriesLabels") or {}
    x_col = (
        roles.get("x")
        or chart.get("xColumn")
        or chart.get("labelColumn")
        or series_labels.get("label")
        or "label"
    )
    y_col = (
        roles.get("y")
        or chart.get("yColumn")
        or chart.get("valueColumn")
        or series_labels.get("value")
        or "value"
    )
    y2_col = (
        roles.get("y2")
        or chart.get("y2Column")
        or chart.get("metricField")
        or series_labels.get("value2")
    )

    cols = [x_col, y_col]
    if y2_col:
        cols.append(y2_col)
    out_rows: list[dict[str, Any]] = []
    for point in series:
        if not isinstance(point, dict):
            continue
        row: dict[str, Any] = {x_col: point.get("label"), y_col: point.get("value")}
        if y2_col:
            row[y2_col] = point.get("value2")
        out_rows.append(row)
    return {"columns": cols, "rows": out_rows} if out_rows else {}


def stored_query_answer(ref: InsightRef) -> dict[str, Any] | None:
    """A deterministic answer containing the card's real SQL, or None.

    Returns ``None`` when the card has no stored SQL so the caller can say so
    rather than fabricating one.
    """
    sql = (ref.card.get("sql") or "").strip()
    if not sql:
        return None
    result = ref.card.get("result") or {}
    if not result or not result.get("rows"):
        result = _result_from_chart(ref.card) or result
    answer = (
        f'This is the stored query that generated the insight "{ref.title}":\n\n'
        f"```sql\n{sql}\n```"
    )
    return {
        "title": f'Query for "{ref.title}"',
        "sql": sql,
        "columns": result.get("columns", []) if isinstance(result, dict) else [],
        "rows": result.get("rows", []) if isinstance(result, dict) else [],
        "explanation": answer,
        "answer": answer,
        "answerType": "text",
        "status": "success",
        "error": None,
        "retrievedFromInsight": ref.title,
    }
