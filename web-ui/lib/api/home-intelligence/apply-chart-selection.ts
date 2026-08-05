"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { VizDecision } from "./viz-decision";



export function applyChartSelection(
  insightId: string,
  body: {
    project_id: number;
    selection: {
      chartType?: string;
      chartSubtype?: string;
      visualizationDecision?: VizDecision;
    };
  },
): Promise<{ updated: boolean; insight_id: string }> {
  return apiClient.post(`/api/ai/insights/${insightId}/chart-selection`, body);
}