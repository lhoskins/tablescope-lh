"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export function getHomeIntelligenceRunStatus(
  runId: string,
): Promise<{ run_id: string; complete: boolean }> {
  return apiClient.get(`/api/ai/home-intelligence/run/${runId}`);
}