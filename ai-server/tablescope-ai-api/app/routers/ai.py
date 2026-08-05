"""AI feature endpoints — all requests flow through the context builder.

Every endpoint:
1. Verifies HMAC signature (request came from trusted app server)
2. Builds permission-aware context via context_builder
3. Sends ONLY allowed context to the LLM
4. Validates LLM output (SQL allowlist, no cross-tenant refs)
5. Logs everything (vectors accessed, context used, denied access)
6. Updates last_activity for idle shutdown

The endpoints live in the ``ai_*`` sibling modules; this module is the parent
aggregator that mounts each feature router under ``/ai`` and re-exports the
feature modules' names so ``app.routers.ai`` stays the single import surface.
"""

import sys
from types import ModuleType

from fastapi import APIRouter

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.services import chart_catalog, context_builder, llm_client, vector_store

from . import (
    ai_actions,
    ai_ask,
    ai_conversation,
    ai_dashboard,
    ai_document,
    ai_file_analysis,
    ai_indexing,
    ai_intelligence_fixsql,
    ai_intelligence_interpret,
    ai_intelligence_knowledge_graph,
    ai_intelligence_plan,
    ai_plan_prompt,
    ai_plan_sql,
    ai_project_insight,
    ai_query_generate,
    ai_reference_library,
    ai_relationships,
    ai_scopes,
    ai_shared,
)
from .ai_actions import (
    _ACTION_DRAFT_SYSTEM_PROMPT,
    _ACTION_DRAFT_USER_PROMPT,
    _build_action_draft_prompt,
    _normalize_enum,
    _sanitize_markdown,
    draft_action,
)
from .ai_ask import ask
from .ai_conversation import (
    _CHART_TYPES,
    _CONVERSATION_INTENTS,
    _CONVERSATION_TURN_SYSTEM_PROMPT,
    _conversation_turn_prompt,
    _sanitize_chart_patch,
    classify_conversation_turn,
)
from .ai_dashboard import (
    _DASHBOARD_INSIGHT_SYSTEM_PROMPT,
    suggest_dashboard,
    suggest_dashboards_multi,
)
from .ai_document import (
    _FAMILY_ROLES,
    _FAMILY_TYPES,
    _normalize_document_family,
    _normalize_family_key,
    profile_document,
    summarize_family,
)
from .ai_file_analysis import analyze_file
from .ai_indexing import (
    index_document,
    index_reference,
)
from .ai_intelligence_fixsql import intelligence_fix_sql
from .ai_intelligence_interpret import intelligence_interpret
from .ai_intelligence_knowledge_graph import (
    _KG_CATEGORIES,
    _KG_SEVERITIES,
    _KG_SYSTEM_PROMPT,
    _build_kg_neighbor_lines,
    knowledge_graph_insights,
)
from .ai_intelligence_plan import (
    _allowed_plan_chart_types,
    intelligence_plan,
)
from .ai_plan_prompt import (
    _build_kg_hypothesis_lines,
    _build_relationship_floor_line,
    _build_relationship_hint_lines,
)
from .ai_plan_sql import (
    _EQ_RE,
    _JOIN_CLAUSE_RE,
    _JOIN_TYPE_RE,
    _SOURCE_DECL_RE,
    _SQL_TABLE_REF_RE,
    _ensure_group_by,
    _ensure_join_on_clause,
    _is_inside_parens,
    _join_conditions_for_hint,
    _join_tables_are_evidence_backed,
    _normalize_expr,
    _on_has_pair,
    _qualify_bare_shared_columns,
    _qualify_shared_columns,
    _split_select_expressions,
    _sql_table_count,
    _strip_quotes,
)
from .ai_project_insight import (
    _PROJECT_INSIGHT_SYSTEM_PROMPT,
    _dict_list,
    _lines,
    _str_list,
    project_insight,
)
from .ai_query_generate import (
    _SOURCE_SUFFIX_RE,
    _catalog_table_columns,
    _needs_clarification,
    _referenced_tables,
    _remap_tables_to_authorized,
    _score_source_match,
    _selected_sources,
    _suggest_sources,
    generate_sql_endpoint,
    match_query,
    normalize_source_name,
)
from .ai_reference_library import (
    suggest_references,
    summarize_reference_document,
)
from .ai_relationships import generate_relationships
from .ai_scopes import analyze_scopes
from .ai_shared import (
    _INTEL_SYSTEM_PROMPT,
    _MAX_HISTORY_TURNS,
    _SELECT_RE,
    _TEIID_FIX_JOIN_RULE,
    _TEIID_JOIN_EXCEPTION_RULE,
    _TEIID_RULES_COMMON,
    _TEIID_RULES_HEADER,
    _TEIID_SINGLE_TABLE_RULE,
    _TEIID_SQL_RULES,
    _WITH_CTE_RE,
    SYSTEM_PROMPT,
    _build_schema_lines,
    _clean_sql,
    _extract_sql,
    _fix_teiid_group_by,
    _format_conversation_history,
    _infer_chart_columns,
    _parse_json_response,
    _repair_truncated_json,
)

router = APIRouter(prefix="/ai", tags=["AI"])

router.include_router(ai_ask.router)
router.include_router(ai_indexing.router)
router.include_router(ai_relationships.router)
router.include_router(ai_query_generate.router)
router.include_router(ai_dashboard.router)
router.include_router(ai_intelligence_plan.router)
router.include_router(ai_intelligence_fixsql.router)
router.include_router(ai_conversation.router)
router.include_router(ai_intelligence_interpret.router)
router.include_router(ai_intelligence_knowledge_graph.router)
router.include_router(ai_project_insight.router)
router.include_router(ai_scopes.router)
router.include_router(ai_file_analysis.router)
router.include_router(ai_document.router)
router.include_router(ai_reference_library.router)
router.include_router(ai_actions.router)

_FEATURE_MODULES = (
    ai_shared,
    ai_ask,
    ai_indexing,
    ai_relationships,
    ai_query_generate,
    ai_dashboard,
    ai_plan_prompt,
    ai_plan_sql,
    ai_intelligence_plan,
    ai_intelligence_fixsql,
    ai_conversation,
    ai_intelligence_interpret,
    ai_intelligence_knowledge_graph,
    ai_project_insight,
    ai_scopes,
    ai_file_analysis,
    ai_document,
    ai_reference_library,
    ai_actions,
)


class _AggregatorModule(ModuleType):
    """Module type that mirrors attribute assignment onto the feature modules.

    The endpoints and helpers re-exported here are defined in the ``ai_*``
    siblings, so a caller that rebinds a name on this module — e.g.
    ``monkeypatch.setattr(app.routers.ai, "verify_signature", ...)`` — must
    reach the module the endpoint actually resolves the name in.
    """

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        for module in _FEATURE_MODULES:
            if hasattr(module, name):
                setattr(module, name, value)


sys.modules[__name__].__class__ = _AggregatorModule

__all__ = [
    "SYSTEM_PROMPT",
    "_ACTION_DRAFT_SYSTEM_PROMPT",
    "_ACTION_DRAFT_USER_PROMPT",
    "_CHART_TYPES",
    "_CONVERSATION_INTENTS",
    "_CONVERSATION_TURN_SYSTEM_PROMPT",
    "_DASHBOARD_INSIGHT_SYSTEM_PROMPT",
    "_EQ_RE",
    "_FAMILY_ROLES",
    "_FAMILY_TYPES",
    "_INTEL_SYSTEM_PROMPT",
    "_JOIN_CLAUSE_RE",
    "_JOIN_TYPE_RE",
    "_KG_CATEGORIES",
    "_KG_SEVERITIES",
    "_KG_SYSTEM_PROMPT",
    "_MAX_HISTORY_TURNS",
    "_PROJECT_INSIGHT_SYSTEM_PROMPT",
    "_SELECT_RE",
    "_SOURCE_DECL_RE",
    "_SOURCE_SUFFIX_RE",
    "_SQL_TABLE_REF_RE",
    "_TEIID_FIX_JOIN_RULE",
    "_TEIID_JOIN_EXCEPTION_RULE",
    "_TEIID_RULES_COMMON",
    "_TEIID_RULES_HEADER",
    "_TEIID_SINGLE_TABLE_RULE",
    "_TEIID_SQL_RULES",
    "_WITH_CTE_RE",
    "_allowed_plan_chart_types",
    "_build_action_draft_prompt",
    "_build_kg_hypothesis_lines",
    "_build_kg_neighbor_lines",
    "_build_relationship_floor_line",
    "_build_relationship_hint_lines",
    "_build_schema_lines",
    "_catalog_table_columns",
    "_clean_sql",
    "_conversation_turn_prompt",
    "_dict_list",
    "_ensure_group_by",
    "_ensure_join_on_clause",
    "_extract_sql",
    "_fix_teiid_group_by",
    "_format_conversation_history",
    "_infer_chart_columns",
    "_is_inside_parens",
    "_join_conditions_for_hint",
    "_join_tables_are_evidence_backed",
    "_lines",
    "_needs_clarification",
    "_normalize_document_family",
    "_normalize_enum",
    "_normalize_expr",
    "_normalize_family_key",
    "_on_has_pair",
    "_parse_json_response",
    "_qualify_bare_shared_columns",
    "_qualify_shared_columns",
    "_referenced_tables",
    "_remap_tables_to_authorized",
    "_repair_truncated_json",
    "_sanitize_chart_patch",
    "_sanitize_markdown",
    "_score_source_match",
    "_selected_sources",
    "_split_select_expressions",
    "_sql_table_count",
    "_str_list",
    "_strip_quotes",
    "_suggest_sources",
    "analyze_file",
    "analyze_scopes",
    "ask",
    "chart_catalog",
    "classify_conversation_turn",
    "context_builder",
    "draft_action",
    "generate_relationships",
    "generate_sql_endpoint",
    "index_document",
    "index_reference",
    "intelligence_fix_sql",
    "intelligence_interpret",
    "intelligence_plan",
    "knowledge_graph_insights",
    "llm_client",
    "match_query",
    "normalize_source_name",
    "profile_document",
    "project_insight",
    "router",
    "settings",
    "suggest_dashboard",
    "suggest_dashboards_multi",
    "suggest_references",
    "summarize_family",
    "summarize_reference_document",
    "update_activity",
    "vector_store",
    "verify_signature",
]
