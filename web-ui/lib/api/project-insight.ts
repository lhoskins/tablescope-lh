import { apiClient } from "@/lib/api-client";
import type { MethodEnvelope } from "./ai-actions";
import type { InsightChart } from "./home-intelligence";

export interface ExecutiveSummary {
  summary: string;
  critical: string[];
  warnings: string[];
  opportunities: string[];
  recommendations: string[];
}

export interface QuestionToAsk {
  id: string;
  question: string;
  reason?: string;
  suggestedAction?: string;
}

export interface QuestionNeedingData {
  id?: string;
  question?: string;
  businessQuestion?: string;
  title?: string;
  reason?: string;
  // Data-driven explanation of what the project would need to answer this.
  missingDataHint?: string;
}

export interface TrendDetection {
  id: string;
  label?: string;
  title?: string;
  description?: string;
  possibleCause?: string;
  sourceSummary?: string;
  chartLink?: string;
  confidence?: number;
}

export interface RecommendedDashboard {
  id: string;
  title?: string;
  description?: string;
  reason?: string;
  status?: string;
  confidence?: number;
  backingSignals?: string[];
  suggestedWidgets?: string[];
  action?: string;
}

export interface RecommendedQuery {
  id: string;
  title?: string;
  businessQuestion?: string;
  reason?: string;
  status?: string;
  confidence?: number;
  backingSignals?: string[];
  recommendedTables?: string[];
  recommendedKpis?: string[];
  action?: string;
  // Source context so the resolver can ground generation in a real source.
  sourceColumns?: string[];
  metric?: string;
}

export interface RecommendedKpi {
  id: string;
  name?: string;
  description?: string;
  status?: string;
  currentValue?: string | number | null;
  targetValue?: string | number | null;
  unit?: string;
  reason?: string;
  confidence?: number;
}

export type InsightCardSeverity =
  | "critical"
  | "urgent"
  | "warning"
  | "watch"
  | "trend"
  | "opportunity"
  | "recommendation"
  | "informational";

export interface ProjectInsightCard {
  id: string;
  /** Stable identifier copied from the source insight card (usually a UUID). */
  insightId?: string;
  insightType: string;
  title: string;
  summary: string;
  severity: InsightCardSeverity;
  recommendedAction?: string;
  question: string;
  supportingSources: string[];
  // Source context (from Business Insight) so Investigate can ground the
  // question in the exact authorized source/columns the finding came from.
  sourceTables?: string[];
  sourceColumns?: string[];
  metric?: string;
  periodColumn?: string;
  /** Structured explainability metadata forwarded from the insight card. */
  explanation?: Record<string, unknown>;
  /** Query/result context when the card is data-backed. */
  sql?: string;
  chart?: InsightChart;
  chartType?: string;
  labelColumn?: string;
  valueColumn?: string;
  valueColumn2?: string;
  executedAt?: string;
  /** Governed Analytical Method Engine envelope (not yet produced for Project Insights). */
  analyticalMethod?: MethodEnvelope;
  evidenceFingerprint?: {
    fingerprintVersion: number;
    planFingerprint: string | null;
    resultFingerprint: string | null;
    semanticFingerprint: string | null;
    seriesFingerprint: string | null;
  };
  confidenceScore?: number;
  confidenceEvaluation?: Record<string, unknown>;
  visualizationDecision?: Record<string, unknown>;
  chartCandidates?: Record<string, unknown>[];
  /** Active time-series view (mode/interval/range) captured for Home pins and dashboards. */
  timeSeriesView?: import("./home-intelligence").TimeSeriesViewState;
}

export interface WhatChangedSinceLastVisit {
  newFilesAdded: number;
  changedDataSources: number;
  newRisksIdentified: number;
  newQueries: number;
  newDashboards: number;
  updatedKnowledgeGraph: number;
  changeLogLink: string;
}

export interface InsightWorkflowItem {
  id: string;
  title?: string;
  type?: string;
  priority?: string;
  confidence?: number;
  status?: string;
  acknowledgedBy?: string | null;
  acknowledgedAt?: string | null;
  evidenceSummary?: string;
  recommendedAction?: string;
}

export interface ProjectInsight {
  project: { id: number; name: string; status: string };
  generatedAt: string;
  lastUpdatedAt: string;
  /** True when the snapshot is stale and a rebuild is in progress/queued. */
  stale?: boolean;
  executiveSummary: ExecutiveSummary;
  questionsToAsk: QuestionToAsk[];
  questionsNeedingData: QuestionNeedingData[];
  trendDetection: TrendDetection[];
  recommendedDashboards: RecommendedDashboard[];
  recommendedQueries: RecommendedQuery[];
  recommendedKpis: RecommendedKpi[];
  risks: ProjectInsightCard[];
  trends: ProjectInsightCard[];
  opportunities: ProjectInsightCard[];
  analysis: ProjectInsightCard[];
  whatChangedSinceLastVisit: WhatChangedSinceLastVisit;
  insightValidationWorkflow: InsightWorkflowItem[];
  aiAvailable: boolean;
  graphStatus: string;
  graphMode: "full" | "limited" | "blocked";
  graphBlockingReasons: string[];
  graphDisclosure: string;
}

export interface AcknowledgeResponse {
  insightId: string;
  status: string;
  acknowledgedByUserId: number | null;
  acknowledgedByName: string;
  acknowledgedAt: string | null;
}

export interface InsightSnapshot {
  title?: string;
  summary?: string;
  category?: string;
  severity?: string;
}

export interface ReviewedInsight {
  insightId: string;
  title: string;
  summary: string;
  category: string;
  severity: string;
  note: string | null;
  reviewedByUserId: number | null;
  reviewedByName: string;
  reviewedAt: string | null;
}

export interface ReviewedInsightsResponse {
  items: ReviewedInsight[];
}

export const projectInsightApi = {
  get: (projectId: string) =>
    apiClient.get<ProjectInsight>(`/api/projects/${projectId}/insight`),
  // Queue a background rebuild (bypasses the saved snapshot); the completed
  // result is persisted server-side and becomes the new snapshot.
  refresh: (projectId: string) =>
    apiClient.post<ProjectInsight>(
      `/api/projects/${projectId}/insight/refresh`,
      {},
    ),
  clearCache: (projectId: string) =>
    apiClient.post<{ deleted: { project_intelligence_snapshots: number; business_insight_results: number } }>(
      `/api/projects/${projectId}/insight/clear-cache`,
      {},
    ),
  acknowledge: (
    projectId: string,
    insightId: string,
    snapshot?: InsightSnapshot,
    note?: string,
  ) =>
    apiClient.post<AcknowledgeResponse>(
      `/api/projects/${projectId}/insights/${encodeURIComponent(insightId)}/acknowledge`,
      { note: note ?? null, ...(snapshot ?? {}) },
    ),
  reviewed: (projectId: string) =>
    apiClient.get<ReviewedInsightsResponse>(
      `/api/projects/${projectId}/insights/reviewed`,
    ),
  reopen: (projectId: string, insightId: string) =>
    apiClient.post<{ insightId: string; status: string }>(
      `/api/projects/${projectId}/insights/${encodeURIComponent(insightId)}/reopen`,
      {},
    ),
};
