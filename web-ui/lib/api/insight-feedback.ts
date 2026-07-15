import { apiClient } from "@/lib/api-client";

export type InsightSentiment = "agree" | "disagree";

export const INSIGHT_FEEDBACK_REASON_CODES: Record<string, string> = {
  incorrect_data: "The data looks incorrect or incomplete",
  missing_context: "Important context is missing",
  wrong_method: "The analytical method doesn't fit",
  not_actionable: "The insight is not actionable",
  disagree_conclusion: "I disagree with the conclusion",
  too_confident: "The confidence is too high",
  other: "Other",
};

export interface InsightFeedbackRecord {
  id: number;
  insight_id: string;
  project_id: number | null;
  insight_type: string | null;
  sentiment: InsightSentiment;
  reason_codes: string[];
  comment: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface UpsertInsightFeedbackPayload {
  project_id: number;
  sentiment: InsightSentiment;
  reason_codes?: string[];
  comment?: string;
  snapshot_id?: string;
  run_id?: string;
  insight_type?: string;
  insight_fingerprint?: string;
  card_snapshot?: Record<string, unknown>;
  explanation_snapshot?: Record<string, unknown>;
  model_metadata?: Record<string, unknown>;
}

export interface BatchInsightFeedbackRequest {
  insight_ids: string[];
}

export interface BatchInsightFeedbackResponse {
  items: InsightFeedbackRecord[];
}

export function getInsightFeedback(
  insightId: string,
): Promise<InsightFeedbackRecord | null> {
  return apiClient.get<InsightFeedbackRecord | null>(`/api/insight-feedback/${insightId}`);
}

export function batchGetInsightFeedback(
  body: BatchInsightFeedbackRequest,
): Promise<BatchInsightFeedbackResponse> {
  return apiClient.post<BatchInsightFeedbackResponse>("/api/insight-feedback/batch", body);
}

export function upsertInsightFeedback(
  insightId: string,
  payload: UpsertInsightFeedbackPayload,
): Promise<InsightFeedbackRecord> {
  return apiClient.put<InsightFeedbackRecord>(`/api/insight-feedback/${insightId}`, payload);
}

export function deleteInsightFeedback(
  insightId: string,
  projectId?: number,
): Promise<void> {
  const qs = projectId != null ? `?project_id=${projectId}` : "";
  return apiClient.delete<void>(`/api/insight-feedback/${insightId}${qs}`);
}
