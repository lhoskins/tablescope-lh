import { apiClient } from "@/lib/api-client";

export type VizType = "table" | "bar" | "line" | "pie" | "kpi";

export interface SuggestedVisualization {
  type: VizType;
  xField?: string;
  yField?: string;
  metricField?: string;
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

export interface AskAndRunResult {
  question: string;
  sql: string;
  columns: string[];
  rows: Record<string, unknown>[];
  suggestedVisualization: SuggestedVisualization;
  explanation: string;
  dataSourcesUsed: string[];
  status: AiActionStatus;
  error: string | null;
  errorDetails?: AiErrorDetails;
  message?: string;
  suggestedSources?: SuggestedSource[];
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
