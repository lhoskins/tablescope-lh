"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export function saveDashboardSuggestion(body: {
  project_id: number;
  title: string;
  summary?: string;
  keyFindings?: string[];
  recommendedActions?: string[];
  widgets: {
    title: string;
    sql: string;
    chartType: string;
    explanation?: string;
    labelColumn?: string;
    valueColumn?: string;
    valueColumn2?: string;
    visualizationOptions?: Record<string, unknown>;
  }[];
}): Promise<{ status: string; dashboard_id: number; name: string }> {
  return apiClient.post("/api/ai/home/save-dashboard", body);
}