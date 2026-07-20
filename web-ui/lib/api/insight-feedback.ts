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
  review_status?: string;
  reviewer_user_id?: number | null;
  reviewer_comment?: string | null;
  reviewed_at?: string | null;
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

export interface InsightFeedbackReviewQueueFilters {
  review_status?: string;
  project_id?: number;
  sentiment?: string;
}

export interface InsightFeedbackReviewQueueResponse {
  items: InsightFeedbackReviewItem[];
  total: number;
}

export interface InsightFeedbackReviewItem extends InsightFeedbackRecord {
  user_id: number;
  card_snapshot?: Record<string, unknown>;
  explanation_snapshot?: Record<string, unknown>;
}

export interface DispositionPayload {
  review_status: string;
  reviewer_comment?: string;
}

export function getInsightFeedbackReviewQueue(
  filters: InsightFeedbackReviewQueueFilters = {},
): Promise<InsightFeedbackReviewQueueResponse> {
  const params = new URLSearchParams();
  if (filters.review_status) params.set("review_status", filters.review_status);
  if (filters.project_id != null) params.set("project_id", String(filters.project_id));
  if (filters.sentiment) params.set("sentiment", filters.sentiment);
  const qs = params.toString();
  return apiClient.get<InsightFeedbackReviewQueueResponse>(
    `/api/insight-feedback/review/queue${qs ? `?${qs}` : ""}`,
  );
}

export function getInsightFeedbackReviewDetail(
  feedbackId: number,
): Promise<InsightFeedbackReviewItem> {
  return apiClient.get<InsightFeedbackReviewItem>(`/api/insight-feedback/review/${feedbackId}`);
}

export function claimInsightFeedbackReview(
  feedbackId: number,
): Promise<InsightFeedbackReviewItem> {
  return apiClient.post<InsightFeedbackReviewItem>(
    `/api/insight-feedback/review/${feedbackId}/claim`,
    {},
  );
}

export function releaseInsightFeedbackReview(
  feedbackId: number,
): Promise<InsightFeedbackReviewItem> {
  return apiClient.post<InsightFeedbackReviewItem>(
    `/api/insight-feedback/review/${feedbackId}/release`,
    {},
  );
}

export function dispositionInsightFeedbackReview(
  feedbackId: number,
  payload: DispositionPayload,
): Promise<InsightFeedbackReviewItem> {
  return apiClient.post<InsightFeedbackReviewItem>(
    `/api/insight-feedback/review/${feedbackId}/disposition`,
    payload,
  );
}
