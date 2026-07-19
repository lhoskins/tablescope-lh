"use client";

import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";

// ── Insight card shape (mirrors the platform-api InsightCard dict) ───────────

export type InsightSeverity =
  | "critical"
  | "urgent"
  | "warning"
  | "watch"
  | "trend"
  | "opportunity"
  | "recommendation"
  | "informational"
  | "info";

export interface InsightChart {
  /**
   * Chart family. ``kpi_grid`` uses the lightweight tile renderer; every other
   * value maps onto the dashboard's WidgetRenderer catalog so Intelligence
   * cards render with the exact same charts as dashboards.
   */
  type:
    | "kpi_grid"
    | "bar"
    | "line"
    | "area"
    | "pie"
    | "combo"
    | "scatter"
    | "radar"
    | "radial_bar"
    | "treemap"
    | "funnel";
  /** Dashboard chart subtype (e.g. "donut", "smooth_line", "waterfall"). */
  subtype?: string;
  title?: string;
  data: {
    /**
     * Each point carries a `value`; two-metric charts (combo/scatter/bubble)
     * also carry `value2` for the second axis/size.
     */
    series?: { label: string; value: number; value2?: number }[];
    threshold?: number;
    kpis?: { value: string; label: string; delta?: string }[];
  };
  /**
   * Axis roles for two-metric charts. Tells the renderer which field maps to
   * each axis (e.g. scatter x=value, y=value2; combo x=label, y=value,
   * y2=value2). Absent for ordinary single-value charts.
   */
  roles?: { x?: string; y?: string; y2?: string; z?: string };
  /** Human-readable column names per series field, for axis/legend labels. */
  seriesLabels?: { value?: string; value2?: string };
}

export interface InsightCallout {
  type: "risk" | "opportunity" | "info";
  text: string;
}

export interface InsightExplanationConfidence {
  level: "low" | "medium" | "high" | null;
  score: number | null;
  basis: string;
}

export interface InsightExplanationSource {
  projectId: string | number;
  projectName: string;
  dataSourceId: string | null;
  dataSourceName: string | null;
  tables: string[];
  fields: string[];
}

export interface InsightExplanationMetric {
  name: string;
  aggregation: string;
  field: string;
}

export interface InsightExplanationEvidence {
  rowCount: number | null;
  resultColumns: string[] | null;
  topFinding?: string | null;
}

export interface InsightExplanationChart {
  chartType: string;
  labelColumn: string | null;
  valueColumn: string | null;
  valueColumn2: string | null;
}

export interface InsightExplanationFilter {
  field: string;
  operator?: string;
  value: unknown;
}

export interface InsightExplanationComparison {
  type: string;
  baselineValue: number;
  currentValue: number;
  baselineLabel: string;
  currentLabel: string;
  field: string;
}

export interface InsightExplanation {
  summary: string;
  method: string;
  methodLabel: string;
  steps: string[];
  source: InsightExplanationSource;
  filters?: InsightExplanationFilter[];
  metrics?: InsightExplanationMetric[];
  comparison?: InsightExplanationComparison;
  evidence: InsightExplanationEvidence;
  sql?: string;
  chart?: InsightExplanationChart;
  assumptions: string[];
  limitations: string[];
  confidence: InsightExplanationConfidence;
  generatedAt: string;
  governance?: {
    requestedMethod: string;
    effectiveMethod: string;
    decision: "allowed" | "fallback" | "blocked";
    policyVersion: number;
    message: string;
    evaluatedAt: string;
  };
}

export interface InsightCard {
  id: string;
  /** Stable, server-generated identifier for this insight instance. */
  insightId?: string;
  projectId: string;
  projectName: string;
  projectColor: string;
  insightType: string;
  severity: InsightSeverity;
  title: string;
  /** Optional natural-language question that investigating this card should ask. */
  question?: string;
  summary: string;
  chart: InsightChart | null;
  callout: InsightCallout | null;
  sources: { tables: string[]; documents: string[] };
  executedAt: string;
  // Optional, backward-compatible metadata emitted by the insight-first
  // pipeline. The UI does not require these and ignores them when absent.
  insightMethod?: string;
  confidenceScore?: number;
  priorityScore?: number;
  validation?: {
    executionStatus?: string;
    rowCount?: number;
    columnsReturned?: string[];
    nonNullMetricCount?: number;
  };
  referenceDocuments?: string[];
  kpiReferences?: string[];
  relationshipMetadata?: {
    leftTable?: string;
    rightTable?: string;
    leftJoinKey?: string;
    rightJoinKey?: string;
    relationshipType?: string;
    joinConfidence?: number;
    confidenceReason?: string;
    rowMultiplicationRisk?: string;
  };
  /** Governed Analytical Method Engine envelope (hybrid mode only). */
  analyticalMethod?: MethodEnvelope;
  /**
   * Raw SQL and chart roles for data-backed cards. These are optional and
   * only present when the insight was generated from a successfully executed
   * query. When absent, the card is not eligible for "Save to dashboard".
   */
  sql?: string;
  chartType?: string;
  labelColumn?: string;
  valueColumn?: string;
  valueColumn2?: string;
  /** Structured explainability metadata produced by the insight pipeline. */
  explanation?: InsightExplanation;
}

export interface ProjectResult {
  projectId: string;
  projectName: string;
  projectColor: string;
  insights: InsightCard[];
}

export interface CrossProjectSynthesis {
  headline: string;
  body: string;
  projectIds: string[];
}

export interface StreamProject {
  id: string;
  name: string;
  color: string;
}

// ── SSE events ───────────────────────────────────────────────────────────────

export type IntelligenceEvent =
  | { type: "start"; projects: StreamProject[] }
  | ({ type: "project_complete" } & ProjectResult)
  | {
      type: "project_error";
      error: string;
      projectId?: string;
      projectName?: string;
    }
  | { type: "synthesis_complete"; synthesis: CrossProjectSynthesis }
  | { type: "done"; projectCount: number };

/**
 * Open the home-intelligence SSE stream and invoke `onEvent` for each event.
 * Returns an `AbortController` so the caller can cancel on unmount / refresh.
 */
export function streamHomeIntelligence(
  onEvent: (event: IntelligenceEvent) => void,
  options: { crossProject?: boolean; granularity?: number } = {},
): AbortController {
  const controller = new AbortController();
  const cross = options.crossProject ?? true;
  const granularity = options.granularity ?? 3;

  (async () => {
    let response: Response;
    try {
      response = await apiClient.stream(
        `/api/ai/home-intelligence/stream?cross_project=${cross}&granularity=${granularity}`,
        { signal: controller.signal },
      );
    } catch (err) {
      if (!controller.signal.aborted) {
        onEvent({ type: "project_error", error: String(err) });
      }
      return;
    }

    if (!response.ok || !response.body) {
      onEvent({
        type: "project_error",
        error: `Stream failed: ${response.status}`,
      });
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE frames are separated by a blank line.
        let sep: number;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          const line = frame
            .split("\n")
            .find((l) => l.startsWith("data:"));
          if (!line) continue;
          const json = line.slice(5).trim();
          if (!json) continue;
          try {
            onEvent(JSON.parse(json) as IntelligenceEvent);
          } catch {
            /* ignore malformed frame */
          }
        }
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        onEvent({ type: "project_error", error: String(err) });
      }
    }
  })();

  return controller;
}

// ── Saved snapshot (latest completed run) ────────────────────────────────────

export interface IntelligenceSnapshot {
  granularity: number;
  updatedAt: string | null;
  generatedAt?: string;
  projects: StreamProject[];
  results: ProjectResult[];
  synthesis: CrossProjectSynthesis | null;
}

export function getIntelligenceSnapshot(): Promise<{
  snapshot: IntelligenceSnapshot | null;
}> {
  return apiClient.get("/api/ai/home-intelligence/snapshot");
}

// ── Single-project re-run (report viewer) ────────────────────────────────────

export function runIntelligenceSuite(
  projectId: number,
  promptTypes?: string[],
  granularity = 3,
): Promise<ProjectResult & { error?: string }> {
  return apiClient.post("/api/ai/run-intelligence-suite", {
    project_id: projectId,
    prompt_types: promptTypes,
    granularity,
  });
}

// ── Intelligence settings (user preferences) ─────────────────────────────────

export interface IntelligenceSettings {
  run_on_load: boolean;
  cross_project: boolean;
  email_digest: boolean;
  /** 1 = executive/high-level .. 5 = granular/detailed. */
  granularity: number;
}

export interface UserPreferences {
  intelligence: IntelligenceSettings;
}

export function getPreferences(): Promise<UserPreferences> {
  return apiClient.get("/api/users/preferences");
}

export function updatePreferences(
  intelligence: Partial<IntelligenceSettings>,
): Promise<UserPreferences> {
  return apiClient.patch("/api/users/preferences", { intelligence });
}

// ── Reports ──────────────────────────────────────────────────────────────────

export interface ReportSection {
  id: string;
  kind: "insight" | "text";
  /** For insight sections: the query definition to re-run on view. */
  insight?: {
    projectId: string;
    projectName: string;
    insightType: string;
    title: string;
  };
  /** For text sections. */
  text?: string;
}

export interface ReportRecord {
  id: number;
  shareToken: string;
  shareUrl: string;
  title: string;
  sections: ReportSection[];
  shareSettings: Record<string, unknown>;
  createdAt: string | null;
  updatedAt: string | null;
}

export function createReport(body: {
  title: string;
  sections: ReportSection[];
  share_settings?: Record<string, unknown>;
}): Promise<ReportRecord> {
  return apiClient.post("/api/reports", body);
}

export function getReport(shareToken: string): Promise<ReportRecord> {
  return apiClient.get(`/api/reports/${shareToken}`);
}

export function listReports(): Promise<ReportRecord[]> {
  return apiClient.get("/api/reports");
}

// ── Home AI suggestions — the three hero pills ───────────────────────────────

export interface QuerySuggestion {
  title: string;
  description: string;
  sql: string;
  chartType?: string;
  labelColumn?: string;
  valueColumn?: string;
}

export interface QuerySuggestionsProject {
  projectId: string;
  projectName: string;
  projectColor: string;
  suggestions: QuerySuggestion[];
}

export function suggestQueries(
  granularity = 3,
  projectId?: number,
): Promise<{ projects: QuerySuggestionsProject[] }> {
  return apiClient.post("/api/ai/home/query-suggestions", {
    granularity,
    max_per_project: 5,
    project_id: projectId ?? null,
  });
}

export interface DashboardWidgetSuggestion {
  title: string;
  subtitle?: string;
  /** Plain-English, data-grounded explanation of what the chart shows. */
  explanation?: string;
  /** Value format for the metric: percent | currency | count | number. */
  format?: string;
  chartType: string;
  chart: InsightChart;
  sql: string;
  labelColumn: string;
  valueColumn: string;
}

export interface DashboardSuggestion {
  title: string;
  summary?: string;
  keyFindings?: string[];
  recommendedActions?: string[];
  widgets: DashboardWidgetSuggestion[];
}

export interface DashboardSuggestionsProject {
  projectId: string;
  projectName: string;
  projectColor: string;
  dashboard: DashboardSuggestion | null;
  // M4: shared presentation descriptor + unified envelope (additive).
  presentation?: PresentationDescriptor;
  envelope?: ResponseEnvelope;
}

export function suggestDashboards(
  granularity = 3,
  projectId?: number,
): Promise<{ projects: DashboardSuggestionsProject[] }> {
  return apiClient.post("/api/ai/home/dashboard-suggestions", {
    granularity,
    max_per_project: 6,
    project_id: projectId ?? null,
  });
}

export function generateProjectDashboard(
  projectId: number,
  maxWidgets = 6,
): Promise<DashboardSuggestionsProject> {
  return apiClient.post("/api/ai/home/project-dashboard", {
    project_id: projectId,
    max_widgets: maxWidgets,
  });
}

export function suggestInsights(
  granularity = 3,
  projectId?: number,
): Promise<{ projects: ProjectResult[] }> {
  return apiClient.post("/api/ai/home/insights", {
    granularity,
    max_per_project: 5,
    project_id: projectId ?? null,
  });
}

export function saveQuerySuggestion(body: {
  project_id: number;
  name: string;
  description?: string;
  sql_text: string;
}): Promise<{ name: string; status: string }> {
  return apiClient.post("/api/ai/actions/save-query", body);
}

export function saveDashboardSuggestion(body: {
  project_id: number;
  title: string;
  summary?: string;
  keyFindings?: string[];
  recommendedActions?: string[];
  widgets: {
    title: string;
    sql: string;
    chartType: string;
    explanation?: string;
    labelColumn?: string;
    valueColumn?: string;
    valueColumn2?: string;
  }[];
}): Promise<{ status: string; dashboard_id: number; name: string }> {
  return apiClient.post("/api/ai/home/save-dashboard", body);
}

export interface SaveCardToDashboardPayload {
  project_id: number;
  dashboard_id?: number | null;
  dashboard_name?: string | null;
  title: string;
  sql: string;
  chartType: string;
  labelColumn?: string | null;
  valueColumn?: string | null;
  valueColumn2?: string | null;
}

export interface SaveCardToDashboardResponse {
  status: string;
  dashboard_id: number;
  name: string;
  project_id: number;
  query_id: number;
  widget_id: string;
}

export function saveCardToDashboard(
  body: SaveCardToDashboardPayload,
): Promise<SaveCardToDashboardResponse> {
  return apiClient.post("/api/ai/home/save-card-to-dashboard", body);
}
