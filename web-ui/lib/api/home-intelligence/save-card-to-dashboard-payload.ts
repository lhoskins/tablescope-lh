"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface SaveCardToDashboardPayload {
  project_id: number;
  source_project_id?: number | null;
  dashboard_id?: number | null;
  dashboard_name?: string | null;
  title: string;
  sql: string;
  chartType: string;
  labelColumn?: string | null;
  valueColumn?: string | null;
  valueColumn2?: string | null;
  visualizationOptions?: Record<string, unknown>;
}