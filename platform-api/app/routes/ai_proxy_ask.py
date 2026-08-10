"""The AI Assistant ask endpoint and prompt routing."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.project import Project, ProjectMember
from app.models.saved_query import SavedQuery
from app.services import ai_intelligence_client
from app.services.ai_grounding import gather_grounding_evidence
from app.services.ai_intelligence_client import AIUnavailableError
from app.services.business_insight_project_resolver import resolve_business_insight_project
from app.services.presentation_engine import PresentationMode
from app.services.presentation_engine import describe as describe_presentation
from app.services.response_envelope import ResponseEnvelope

from .ai_proxy_ask_and_run import (
    _ask_and_run_core,
    _forward_prose_answer,
)
from .ai_proxy_schemas import (
    AIAskRequest,
    RoutePromptRequest,
    RoutePromptResponse,
)
from .ai_proxy_shared import (
    _check_project_access,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Row cap for a data answer rendered inline in the AI Assistant chat.
CHAT_ANSWER_MAX_ROWS = 100


_QUERY_SUMMARY_PATTERNS = [
    re.compile(r"\bsummary of (my|all|the) queries\b", re.IGNORECASE),
    re.compile(
        r"\b(summarize|summarise|list|show|overview of|recap) "
        r"(my|all|the) queries\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bhow many queries (do i|have i)\b", re.IGNORECASE),
]


def _is_query_summary_request(question: str) -> bool:
    """True when the prompt is asking for an overview of the user's queries."""
    q = (question or "").strip()
    return any(p.search(q) for p in _QUERY_SUMMARY_PATTERNS)


def _plural(n: int, singular: str, plural: str) -> str:
    return singular if n == 1 else plural


async def _build_query_summary(
    session: AsyncSession,
    context: RequestContext,
    *,
    include_archived: bool = False,
) -> str:
    """Build a friendly, authorization-scoped summary of the user's queries.

    Includes queries in every project the caller can access (private projects
    they own + shared projects they are an active member of). Archived queries
    are excluded unless explicitly requested.
    """
    member_sub = select(ProjectMember.project_id).where(
        ProjectMember.user_id == context.user_id,
        ProjectMember.is_active.is_(True),
    )
    projects = list(
        await session.scalars(
            select(Project)
            .where(
                Project.tenant_id == context.tenant_id,
                or_(
                    Project.owner_id == context.user_id,
                    Project.id.in_(member_sub),
                ),
            )
            .order_by(Project.name)
        )
    )
    if not projects:
        return (
            "You don't have access to any projects yet, so there are no "
            "queries to summarize."
        )

    ids = [p.id for p in projects]
    count_stmt = select(SavedQuery.project_id, func.count()).where(
        SavedQuery.project_id.in_(ids)
    )
    if not include_archived:
        count_stmt = count_stmt.where(SavedQuery.is_archived.is_(False))
    count_stmt = count_stmt.group_by(SavedQuery.project_id)
    counts = {pid: c for pid, c in (await session.execute(count_stmt)).all()}

    total = sum(counts.values())
    private = [
        (p, counts.get(p.id, 0)) for p in projects if not p.is_shared
    ]
    shared = [(p, counts.get(p.id, 0)) for p in projects if p.is_shared]

    lines: list[str] = []
    if total == 0:
        lines.append(
            "You don't have any "
            + ("" if include_archived else "active ")
            + "queries yet across your "
            + f"{len(projects)} accessible "
            + _plural(len(projects), "project", "projects")
            + "."
        )
        return "\n".join(lines)

    scope_word = "" if include_archived else "active "
    lines.append(
        f"You currently have {total} {scope_word}"
        f"{_plural(total, 'query', 'queries')} across your "
        f"{len(projects)} accessible "
        f"{_plural(len(projects), 'project', 'projects')}."
    )

    def _section(heading: str, rows: list[tuple[Project, int]]) -> None:
        with_queries = [(p, c) for p, c in rows if c > 0]
        if not with_queries:
            return
        lines.append("")
        lines.append(f"{heading}:")
        for p, c in with_queries:
            lines.append(f"- {p.name}: {c} {_plural(c, 'query', 'queries')}")

    _section("Private projects", private)
    _section("Shared projects", shared)

    lines.append("")
    if include_archived:
        lines.append(
            "This summary includes archived queries as requested."
        )
    else:
        lines.append(
            "All queries listed are active and available for execution. "
            "Archived queries are not included."
        )
    return "\n".join(lines)


async def _ask_data_first(
    session: AsyncSession,
    context: RequestContext,
    *,
    project_id: int,
    question: str,
) -> dict[str, Any] | None:
    """Try to answer a chat question with executed data (chart + grid + SQL).

    Mirrors the conversations endpoint: auto-resolve a source, generate + execute
    SQL, and return the real result under the shared ``ResponseEnvelope`` so the
    chat renders a widget instead of printing SQL as prose. Returns ``None`` when
    the question can't be grounded on data (so the caller falls back to the prose
    documents/knowledge-graph answer). Fail-closed — never raises.
    """
    try:
        run = await _ask_and_run_core(
            session, context,
            project_id=project_id,
            question=question,
            max_rows=CHAT_ANSWER_MAX_ROWS,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.info("Chat data-first attempt failed, falling back to prose: %s", exc)
        return None
    # Retrieval answers (stored SQL) are valid even when the cache did not keep
    # the full result frame; the SQL itself is what the user asked for.
    is_retrieval = bool(run.get("retrievedFromInsight"))
    is_text = run.get("answerType") == "text"
    if run.get("status") != "success" or (not run.get("rows") and not is_retrieval and not is_text):
        return None
    return {
        "answer": run.get("answer") if is_text else _chat_answer_text(question, run),
        "model_used": run.get("model_used", "tablescope-data"),
        "request_id": "",
        "context_summary": {},
        "audit_id": None,
        "presentation": run.get("presentation"),
        "envelope": run.get("envelope"),
        "answerType": run.get("answerType"),
        "retrievedFromInsight": run.get("retrievedFromInsight"),
        "sql": run.get("sql") if is_retrieval else None,
        "columns": run.get("columns"),
        "rows": run.get("rows"),
    }


@router.post("/ask")
async def ask(
    req: AIAskRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Ask Tablescope AI a question about the active project."""
    await _check_project_access(session, context, req.project_id)

    # A request for a summary of the user's queries is answered directly from
    # the database (authorization-correct, no AI-server dependency).
    if _is_query_summary_request(req.question):
        response = {
            "answer": await _build_query_summary(session, context),
            "model_used": "tablescope-direct",
            "request_id": "",
            "context_summary": {},
        }
        _attach_ask_envelope(response)
        return response

    # Gather proactive grounding once for the prose path. The data path below
    # reuses the executed result plus these references for synthesis.
    grounding = await gather_grounding_evidence(
        session,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=req.project_id,
        question=req.question,
    )
    grounding_dict = grounding.model_dump() if grounding else None

    # Data-first backbone (same as the conversations chat): a question the
    # resolver can ground on a source is answered with a real executed result —
    # chart + table + hidden SQL — rather than a prose answer that merely prints
    # the SQL. Anything the resolver can't ground falls through to prose below.
    # Document/reference-library questions bypass SQL generation entirely.
    from app.services.conversational_analytics.intent_classification import (
        _is_document_question,
    )

    data_response = None
    if not _is_document_question(req.question):
        data_response = await _ask_data_first(
            session, context, project_id=req.project_id, question=req.question
        )
    if data_response is not None:
        # Synthesize a natural-language answer from the executed result, falling
        # back to the deterministic short answer if the AI server is unavailable.
        try:
            synthesized = await ai_intelligence_client.ask(
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                project_id=req.project_id,
                question=req.question,
                scope=req.scope,
                history=req.history,
                grounding_evidence=grounding_dict,
                data_result=data_response,
            )
            if synthesized and synthesized.get("answer"):
                data_response["answer"] = str(synthesized["answer"]).strip()
                data_response["model_used"] = synthesized.get("model_used", data_response.get("model_used", "tablescope-synthesized"))
        except AIUnavailableError:
            logger.info("AI synthesis unavailable for ask data result; using deterministic answer")
        return data_response

    answer = await _forward_prose_answer(
        session,
        context,
        project_id=req.project_id,
        question=req.question,
        history=req.history,
        scope=req.scope,
        include_query_history=req.include_query_history,
        include_dashboard_context=req.include_dashboard_context,
        grounding_evidence=grounding_dict,
    )
    if not answer:
        answer = "The AI service is temporarily unavailable. Please try again shortly."
    response = {
        "answer": answer,
        "model_used": "tablescope-prose",
        "request_id": "",
        "context_summary": {},
    }
    _attach_ask_envelope(response)
    return response


@router.post("/route-prompt", response_model=RoutePromptResponse)
async def route_prompt(
    req: RoutePromptRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> RoutePromptResponse:
    """Route a Home hero prompt to the right destination.

    If the caller already has a project (or named one), the prompt opens that
    project's AI assistant pre-filled. Otherwise it seeds new-project creation.
    """
    prompt = req.prompt.strip()
    target_id = req.project_id
    if target_id is not None:
        await _check_project_access(session, context, target_id)
    else:
        # Resolve the best authorized project from the prompt text, then fall back
        # to the most recently updated project if the resolver is not confident.
        resolved = await resolve_business_insight_project(
            session, context, prompt
        )
        if resolved.status == "resolved" and resolved.project_id:
            target_id = resolved.project_id
        else:
            member_sub = select(ProjectMember.project_id).where(
                ProjectMember.user_id == context.user_id,
                ProjectMember.is_active.is_(True),
            )
            target_id = await session.scalar(
                select(Project.id)
                .where(
                    Project.tenant_id == context.tenant_id,
                    or_(
                        Project.owner_id == context.user_id,
                        Project.id.in_(member_sub),
                    ),
                )
                .order_by(Project.updated_at.desc())
                .limit(1)
            )

    if target_id is not None:
        return RoutePromptResponse(
            route=f"/projects/{target_id}/ai", prefilled=prompt
        )
    return RoutePromptResponse(route="/projects/new", prefilled=prompt)


def _attach_ask_envelope(response: dict[str, Any]) -> None:
    """Stamp the conversational ``presentation`` descriptor + ``ResponseEnvelope``
    on an ``/ask`` chat response.

    The conversational surface always returns a prose ``answer``; this maps it
    onto the shared contract (``mode="conversational"``, ``prose_answer`` section)
    so the frontend can render it through the same ``ResponsePresenter`` as every
    other migrated surface. Additive, fail-closed — never raises, existing fields
    untouched.
    """
    try:
        if not isinstance(response, dict):
            return
        mode = PresentationMode.CONVERSATIONAL
        response["presentation"] = describe_presentation(mode)
        response["envelope"] = ResponseEnvelope.build(
            mode,
            answer=response.get("answer") or None,
        ).model_dump(exclude_none=True)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Presentation engine hook (ask) failed: %s", exc)


def _chat_answer_text(question: str, run: dict[str, Any]) -> str:
    """Short natural-language answer for an executed chat query.

    Prefers the generator's plain-English explanation; otherwise states the
    single scalar result (KPI-style questions) or how many rows were returned.
    The full result table + chart are attached separately as structured data.
    """
    explanation = (run.get("explanation") or "").strip()
    columns = run.get("columns") or []
    rows = run.get("rows") or []
    if not rows:
        return explanation or "The query ran but returned no rows."
    if len(rows) == 1 and len(columns) == 1:
        value = rows[0].get(columns[0])
        scalar = f"{columns[0]}: {value}"
        return f"{explanation}\n\n{scalar}".strip() if explanation else scalar
    summary = f"Here are the results ({len(rows)} rows)."
    return f"{explanation}\n\n{summary}".strip() if explanation else summary
