"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { DashboardSuggestionsProject } from "./dashboard-suggestions-project";



export function suggestDashboards(
  granularity = 3,
  projectId?: number,
): Promise<{ projects: DashboardSuggestionsProject[] }> {
  return apiClient.post("/api/ai/home/dashboard-suggestions", {
    granularity,
    max_per_project: 6,
    project_id: projectId ?? null,
  });
}