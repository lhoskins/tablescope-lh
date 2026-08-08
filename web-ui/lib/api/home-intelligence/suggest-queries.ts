"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { QuerySuggestionsProject } from "./query-suggestions-project";



export function suggestQueries(
  granularity = 3,
  projectId?: number,
): Promise<{ projects: QuerySuggestionsProject[] }> {
  return apiClient.post("/api/ai/home/query-suggestions", {
    granularity,
    max_per_project: 5,
    project_id: projectId ?? null,
  });
}