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
): Promise<{ projects: ProjectResult[] }> {
  return apiClient.post("/api/ai/home/insights", {
    granularity,
    max_per_project: 5,
    project_id: projectId ?? null,
  });
}