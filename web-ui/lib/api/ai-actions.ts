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
  | "execution_error";

export interface AiErrorDetails {
  matchedSources?: string[];
  sql?: string;
  validationError?: string;
  executionError?: string;
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
}

export interface SaveQueryResult {
  action: string;
  status: string;
  query_id: number;
  name: string;
  sql_text: string;
}

export const aiActionsApi = {
  askAndRun: (projectId: string, question: string, source?: string) =>
    apiClient.post<AskAndRunResult>("/api/ai/actions/ask-and-run", {
      project_id: Number(projectId),
      question,
      source: source ?? null,
    }),

  generateQueryPreview: (
    projectId: string,
    question: string,
    title?: string,
    description?: string,
  ) =>
    apiClient.post<GenerateQueryPreviewResult>(
      "/api/ai/actions/generate-query-preview",
      {
        project_id: Number(projectId),
        question,
        title: title ?? null,
        description: description ?? null,
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
