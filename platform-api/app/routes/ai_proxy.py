"""AI proxy routes — the ONLY path from the frontend to the AI server.

The frontend never calls the AI server directly. This proxy:
1. Validates the user's session and permissions
2. Resolves tenant, project, and user scope
3. Signs the request with HMAC
4. Forwards to the AI server
5. Returns the AI response

Also provides a /permissions endpoint called by the AI server to verify
access before retrieving vectors or building context.

The endpoints live in the ``ai_proxy_*`` sibling modules; this module is the
parent aggregator that mounts each feature router under ``/ai`` and re-exports
the feature modules' names so ``app.routes.ai_proxy`` stays the single import
surface.
"""

from __future__ import annotations

import sys
from types import ModuleType

from fastapi import APIRouter

from app.services import ai_intelligence_client as ai

from . import (
    ai_proxy_ask,
    ai_proxy_ask_and_run,
    ai_proxy_dashboard,
    ai_proxy_dashboard_generate,
    ai_proxy_dashboard_save,
    ai_proxy_dashboard_suggest,
    ai_proxy_index,
    ai_proxy_permissions,
    ai_proxy_query,
    ai_proxy_query_actions,
    ai_proxy_schemas,
    ai_proxy_scopes,
    ai_proxy_shared,
    ai_proxy_widget_helpers,
)
from .ai_proxy_ask import (
    _QUERY_SUMMARY_PATTERNS,
    CHAT_ANSWER_MAX_ROWS,
    _ask_data_first,
    _attach_ask_envelope,
    _build_query_summary,
    _chat_answer_text,
    _is_query_summary_request,
    _plural,
    ask,
    route_prompt,
)
from .ai_proxy_ask_and_run import (
    _CODE_FENCE_RE,
    _LEADING_SQL_COMMENT_RE,
    _LIMIT_RE,
    _READONLY_START_RE,
    _ai_generation_error,
    _apply_row_limit,
    _ask_and_run_core,
    _attach_analytical_envelope,
    _attach_ask_analytics,
    _attach_presentation,
    _build_ask_and_run_envelope,
    _classify_intent_safe,
    _column_samples_for_tables,
    _execute_project_sql,
    _execute_with_repair,
    _forward_prose_answer,
    _generate_sql_for_question,
    _insight_card_context,
    _is_read_only_select,
    _project_table_schema,
    _resolve_action_sources,
    _retrieve_stored_insight_query,
    _strip_model_markup,
    _suggest_visualization,
    ai_ask_and_run,
    ai_generate_query_preview,
)
from .ai_proxy_dashboard import (
    suggest_dashboard,
)
from .ai_proxy_dashboard_generate import (
    ai_generate_and_save_dashboard,
)
from .ai_proxy_dashboard_save import (
    ai_save_dashboard_suggestion,
)
from .ai_proxy_dashboard_suggest import (
    _render_preview_widgets,
    ai_suggest_dashboards,
)
from .ai_proxy_index import (
    index_document,
)
from .ai_proxy_permissions import (
    ai_status,
    check_permissions,
)
from .ai_proxy_query import (
    generate_relationships,
    generate_sql,
)
from .ai_proxy_query_actions import (
    _GENERATION_INTENT_PATTERN,
    _SOURCE_SUFFIX_RE,
    _clarification_response,
    _heuristic_rank_sources,
    _heuristic_sql,
    _normalize_source_name,
    _resolve_prompt_source,
    _score_source_match,
    _strip_source_suffix,
    ai_generate_and_save_query,
    ai_save_query,
    normalize_ai_generation_intent,
)
from .ai_proxy_schemas import (
    AIAskAndRunRequest,
    AIAskRequest,
    AICardContext,
    AICreateScopeRequest,
    AIGenerateAndSaveDashboardRequest,
    AIGenerateAndSaveQueryRequest,
    AIGenerateQueryPreviewRequest,
    AIGenerateRelationshipsRequest,
    AIGenerateSQLRequest,
    AIIndexDocumentRequest,
    AIPermissionsResponse,
    AISaveDashboardSuggestionRequest,
    AISaveQueryRequest,
    AISuggestDashboardRequest,
    AISuggestDashboardsRequest,
    AISuggestionPayload,
    AISuggestionWidget,
    RoutePromptRequest,
    RoutePromptResponse,
)
from .ai_proxy_scopes import (
    _ai_analyze_and_create_scopes,
    _analyze_project_scopes,
    _extract_select_columns,
    _has_string_values,
    _is_numeric_column,
    _is_summarized_query,
    _sample_query_values,
    _string_values,
    _value_overlap,
    auto_create_scopes_from_queries,
    generate_scope_map,
)
from .ai_proxy_shared import (
    TIMEOUT,
    _build_source_catalog,
    _check_project_access,
    _detect_datasource,
    _forward_to_ai,
    _kg_context,
    _kg_context_chips,
    _shorten_ai_name,
    _sign_payload,
)
from .ai_proxy_widget_helpers import (
    _CHART_TYPE_MAP,
    _ENGINE_TO_PLANNER,
    _FAMILY_GROUPS,
    _NARRATIVE_TYPES,
    _TIME_SERIES_TYPES,
    _build_join_metadata,
    _correct_widget_chart,
    _derive_dashboard_title,
    _judge_widget,
    _map_chart_subtype,
    _map_chart_type,
    _map_widget_visual,
    _norm_col,
    _pack_grid,
    _suggestion_save_prompt,
)

router = APIRouter(prefix="/ai", tags=["AI"])

router.include_router(ai_proxy_ask.router)
router.include_router(ai_proxy_query.router)
router.include_router(ai_proxy_scopes.router)
router.include_router(ai_proxy_dashboard.router)
router.include_router(ai_proxy_index.router)
router.include_router(ai_proxy_permissions.router)
router.include_router(ai_proxy_query_actions.router)
router.include_router(ai_proxy_ask_and_run.router)
router.include_router(ai_proxy_dashboard_generate.router)
router.include_router(ai_proxy_dashboard_suggest.router)
router.include_router(ai_proxy_dashboard_save.router)

_FEATURE_MODULES = (
    ai_proxy_ask,
    ai_proxy_ask_and_run,
    ai_proxy_dashboard,
    ai_proxy_dashboard_generate,
    ai_proxy_dashboard_save,
    ai_proxy_dashboard_suggest,
    ai_proxy_index,
    ai_proxy_permissions,
    ai_proxy_query,
    ai_proxy_query_actions,
    ai_proxy_schemas,
    ai_proxy_scopes,
    ai_proxy_shared,
    ai_proxy_widget_helpers,
)


class _AggregatorModule(ModuleType):
    """Module type that mirrors attribute assignment onto the feature modules.

    The endpoints and helpers re-exported here are defined in the
    ``ai_proxy_*`` siblings, so a caller that rebinds a name on this module —
    e.g. ``monkeypatch.setattr(app.routes.ai_proxy, "_forward_to_ai", ...)`` —
    must reach the modules the endpoints actually resolve the name in.
    """

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        for module in _FEATURE_MODULES:
            if hasattr(module, name):
                setattr(module, name, value)


sys.modules[__name__].__class__ = _AggregatorModule

__all__ = [
    "AIAskAndRunRequest",
    "AIAskRequest",
    "AICardContext",
    "AICreateScopeRequest",
    "AIGenerateAndSaveDashboardRequest",
    "AIGenerateAndSaveQueryRequest",
    "AIGenerateQueryPreviewRequest",
    "AIGenerateRelationshipsRequest",
    "AIGenerateSQLRequest",
    "AIIndexDocumentRequest",
    "AIPermissionsResponse",
    "AISaveDashboardSuggestionRequest",
    "AISaveQueryRequest",
    "AISuggestDashboardRequest",
    "AISuggestDashboardsRequest",
    "AISuggestionPayload",
    "AISuggestionWidget",
    "CHAT_ANSWER_MAX_ROWS",
    "RoutePromptRequest",
    "RoutePromptResponse",
    "TIMEOUT",
    "_CHART_TYPE_MAP",
    "_CODE_FENCE_RE",
    "_ENGINE_TO_PLANNER",
    "_FAMILY_GROUPS",
    "_GENERATION_INTENT_PATTERN",
    "_LEADING_SQL_COMMENT_RE",
    "_LIMIT_RE",
    "_NARRATIVE_TYPES",
    "_QUERY_SUMMARY_PATTERNS",
    "_READONLY_START_RE",
    "_SOURCE_SUFFIX_RE",
    "_TIME_SERIES_TYPES",
    "_ai_analyze_and_create_scopes",
    "_ai_generation_error",
    "_analyze_project_scopes",
    "_apply_row_limit",
    "_ask_and_run_core",
    "_ask_data_first",
    "_attach_analytical_envelope",
    "_attach_ask_analytics",
    "_attach_ask_envelope",
    "_attach_presentation",
    "_build_ask_and_run_envelope",
    "_build_join_metadata",
    "_build_query_summary",
    "_build_source_catalog",
    "_chat_answer_text",
    "_check_project_access",
    "_clarification_response",
    "_classify_intent_safe",
    "_column_samples_for_tables",
    "_correct_widget_chart",
    "_derive_dashboard_title",
    "_detect_datasource",
    "_execute_project_sql",
    "_execute_with_repair",
    "_extract_select_columns",
    "_forward_prose_answer",
    "_forward_to_ai",
    "_generate_sql_for_question",
    "_has_string_values",
    "_heuristic_rank_sources",
    "_heuristic_sql",
    "_insight_card_context",
    "_is_numeric_column",
    "_is_query_summary_request",
    "_is_read_only_select",
    "_is_summarized_query",
    "_judge_widget",
    "_kg_context",
    "_kg_context_chips",
    "_map_chart_subtype",
    "_map_chart_type",
    "_map_widget_visual",
    "_norm_col",
    "_normalize_source_name",
    "_pack_grid",
    "_plural",
    "_project_table_schema",
    "_render_preview_widgets",
    "_resolve_action_sources",
    "_resolve_prompt_source",
    "_retrieve_stored_insight_query",
    "_sample_query_values",
    "_score_source_match",
    "_shorten_ai_name",
    "_sign_payload",
    "_string_values",
    "_strip_model_markup",
    "_strip_source_suffix",
    "_suggest_visualization",
    "_suggestion_save_prompt",
    "_value_overlap",
    "ai",
    "ai_ask_and_run",
    "ai_generate_and_save_dashboard",
    "ai_generate_and_save_query",
    "ai_generate_query_preview",
    "ai_save_dashboard_suggestion",
    "ai_save_query",
    "ai_status",
    "ai_suggest_dashboards",
    "ask",
    "auto_create_scopes_from_queries",
    "check_permissions",
    "generate_relationships",
    "generate_scope_map",
    "generate_sql",
    "index_document",
    "normalize_ai_generation_intent",
    "route_prompt",
    "router",
    "suggest_dashboard",
]
