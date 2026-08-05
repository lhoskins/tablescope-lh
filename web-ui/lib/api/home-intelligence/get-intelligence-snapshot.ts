"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { IntelligenceSnapshot } from "./intelligence-snapshot";



export function getIntelligenceSnapshot(): Promise<{
  snapshot: IntelligenceSnapshot | null;
}> {
  return apiClient.get("/api/ai/home-intelligence/snapshot");
}