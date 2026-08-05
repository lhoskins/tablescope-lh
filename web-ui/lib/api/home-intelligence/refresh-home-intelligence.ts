"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { IntelligenceSnapshot } from "./intelligence-snapshot";



export function refreshHomeIntelligence(options: {
  crossProject?: boolean;
  granularity?: number;
} = {}): Promise<{ snapshot: IntelligenceSnapshot | null; run_id: string | null }> {
  return apiClient.post("/api/ai/home-intelligence/refresh", {
    cross_project: options.crossProject ?? true,
    granularity: options.granularity ?? 3,
  });
}