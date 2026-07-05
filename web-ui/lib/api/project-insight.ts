import { apiClient } from "@/lib/api-client";

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
  executiveSummary: ExecutiveSummary;
  questionsToAsk: QuestionToAsk[];
  trendDetection: TrendDetection[];
  recommendedDashboards: RecommendedDashboard[];
  recommendedQueries: RecommendedQuery[];
  recommendedKpis: RecommendedKpi[];
  whatChangedSinceLastVisit: WhatChangedSinceLastVisit;
  insightValidationWorkflow: InsightWorkflowItem[];
  aiAvailable: boolean;
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
