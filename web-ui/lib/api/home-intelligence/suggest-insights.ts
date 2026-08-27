"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { ProjectResult } from "./project-result";



export function suggestInsights(
  granularity = 3,
  projectId?: number,
  refresh = false,
): Promise<{ projects: ProjectResult[] }> {
  const path = refresh
    ? "/api/ai/home/insights?refresh=true"
    : "/api/ai/home/insights";
  return apiClient.post(path, {
    granularity,
    max_per_project: 5,
    project_id: projectId ?? null,
  });
}