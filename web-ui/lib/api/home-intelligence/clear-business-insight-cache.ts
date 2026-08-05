"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export function clearBusinessInsightCache(): Promise<{
  deleted: {
    business_insight_results: number;
    intelligence_snapshots: number;
    project_insight_snapshots: number;
  };
}> {
  return apiClient.post("/api/ai/home-intelligence/clear-cache", {});
}