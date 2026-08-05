"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { PercentChangeSummaryRequest } from "./percent-change-summary-request";
import { PercentChangeSummaryResponse } from "./percent-change-summary-response";



export function getPercentChangeSummary(
  body: PercentChangeSummaryRequest,
  signal?: AbortSignal,
): Promise<PercentChangeSummaryResponse> {
  return apiClient.post("/api/ai/insights/percent-change-summary", body, { signal });
}