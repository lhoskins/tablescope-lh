import { apiClient } from "@/lib/api-client";

/**
 * Chart families a conversational answer can request.
 *
 * This mirrors the backend `ChartType` vocabulary (and therefore the ECharts
 * renderer registry) rather than a hand-picked subset: the shared ask pipeline
 * now ranks every family for chat, so narrowing here would silently turn a
 * scatter or heatmap answer back into a bar.
 */
export type VizType =
  | "table"
  | "kpi"
  | "line"
  | "area"
  | "bar"
  | "combo"
  | "pie"
  | "scatter"
  | "effect_scatter"
  | "radar"
  | "radial_bar"
  | "treemap"
  | "sunburst"
  | "tree"
  | "funnel"
  | "sankey"
  | "graph"
  | "parallel"
  | "lines"
  | "heatmap"
  | "candlestick"
  | "boxplot"
  | "pictorial_bar"
  | "theme_river"
  | "gauge"
  | "map";

export interface SuggestedVisualization {
  type: VizType;
  xField?: string;
  yField?: string;
  metricField?: string;
  /** Engine-chosen variant, e.g. "horizontal_bar" for many categories. */
  chartStyle?: string;
  /** Rank by the measure and keep only the top N categories when set. */
  topN?: number;
  /** Second measure for dual-axis families (combo, dual line). */
  y2Field?: string;
  /** Axis/label formatting class chosen by the engine. */
  valueFormat?: string;
  /** Ranked alternatives for the in-chat chart picker. */
  candidates?: unknown[];
}

export type AiActionStatus =
  | "success"
  | "generation_error"
  | "execution_error"
  | "needs_clarification";

export interface AiErrorDetails {
  matchedSources?: string[];
  sql?: string;
  validationError?: string;
  executionError?: string;
}

/** Source context carried from a Business/Project Insight card. */
export interface AiCardContext {
  insight_type?: string;
  source_tables?: string[];
  source_columns?: string[];
  metric?: string;
  period_column?: string;
}

/** A source the resolver offers when a request is ambiguous. */
export interface SuggestedSource {
  name: string;
  reason: string;
}

/** Compact analytical-method envelope carried by a hybrid answer (M1). */
export interface MethodEnvelope {
  method?: string | null;
  methodName?: string | null;
  tier?: number | null;
  analysisIntent?: string | null;
  status?: string | null;
  n?: number | null;
  usableN?: number | null;
  quality?: string | null;
  results?: Record<string, unknown> | null;
  assumptions?: unknown[];
  caveats?: unknown[];
  warnings?: unknown[];
  executionEngine?: string | null;
  /** When the runtime fell back from one engine to another (e.g. "r" -> "python"). */
  fallbackFrom?: string | null;
  resultSchemaVersion?: number | null;
  chartContract?: Record<string, unknown> | null;
}

/**
 * Unified response contract (M4). The section-per-mode registry decides which
 * of these fields render and in what order via `sections`; every field is
 * optional so each surface fills only what it produces.
 */
export interface ResponseEnvelope {
  mode: string;
  sections: string[];
  summary?: string;
  executive_summary?: string;
  answer?: string;
  key_points?: unknown[];
  key_findings?: unknown[];
  key_drivers?: unknown[];
  recommended_actions?: unknown[];
  sql?: string;
  columns?: string[];
  rows?: Record<string, unknown>[];
  chart?: SuggestedVisualization;
  chart_cards?: unknown[];
  method_envelope?: MethodEnvelope;
  sources?: unknown[];
  references?: unknown[];
  intent?: Record<string, unknown>;
  status?: string;
}

/** Presentation descriptor stamped alongside a response (M4). */
export interface PresentationDescriptor {
  mode: string;
  sections: string[];
}

export interface AskAndRunResult {
  question: string;
  sql: string;
  columns: string[];
  rows: Record<string, unknown>[];
  suggestedVisualization: SuggestedVisualization;
  explanation: string;
  dataSourcesUsed: string[];
  status: AiActionStatus;
  // "data" for an executed query (rows + chart); "text" for a prose answer
  // from the documents/knowledge-graph fallback when no data source matched.
  answerType?: "data" | "text";
  error: string | null;
  errorDetails?: AiErrorDetails;
  message?: string;
  suggestedSources?: SuggestedSource[];
  // M4: shared presentation descriptor + unified envelope (additive).
  presentation?: PresentationDescriptor;
  envelope?: ResponseEnvelope;
  analyticalMethod?: MethodEnvelope;
  intent?: Record<string, unknown>;
}

export interface GenerateQueryPreviewResult {
  title: string;
  description: string;
  sql: string;
  columns: string[];
  rows: Record<string, unknown>[];
  suggestedVisualization: SuggestedVisualization;
  dataSourcesUsed: string[];
  explanation: string;
  status: AiActionStatus;
  error: string | null;
  errorDetails?: AiErrorDetails;
  message?: string;
  suggestedSources?: SuggestedSource[];
  // M4: shared presentation descriptor + unified envelope (additive).
  presentation?: PresentationDescriptor;
  envelope?: ResponseEnvelope;
}

export interface SaveQueryResult {
  action: string;
  status: string;
  query_id: number;
  name: string;
  sql_text: string;
}

export const aiActionsApi = {
  askAndRun: (
    projectId: string,
    question: string,
    source?: string,
    cardContext?: AiCardContext,
  ) =>
    apiClient.post<AskAndRunResult>("/api/ai/actions/ask-and-run", {
      project_id: Number(projectId),
      question,
      source: source ?? null,
      card_context: cardContext ?? null,
    }),

  generateQueryPreview: (
    projectId: string,
    question: string,
    title?: string,
    description?: string,
    cardContext?: AiCardContext,
  ) =>
    apiClient.post<GenerateQueryPreviewResult>(
      "/api/ai/actions/generate-query-preview",
      {
        project_id: Number(projectId),
        question,
        title: title ?? null,
        description: description ?? null,
        card_context: cardContext ?? null,
      },
    ),

  saveQuery: (
    projectId: string,
    name: string,
    sqlText: string,
    description?: string,
  ) =>
    apiClient.post<SaveQueryResult>("/api/ai/actions/save-query", {
      project_id: Number(projectId),
      name,
      sql_text: sqlText,
      description: description ?? null,
    }),
};
