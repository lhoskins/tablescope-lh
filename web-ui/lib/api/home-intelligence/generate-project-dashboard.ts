"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { DashboardSuggestionsProject } from "./dashboard-suggestions-project";



export function generateProjectDashboard(
  projectId: number,
  maxWidgets = 6,
): Promise<DashboardSuggestionsProject> {
  return apiClient.post("/api/ai/home/project-dashboard", {
    project_id: projectId,
    max_widgets: maxWidgets,
  });
}