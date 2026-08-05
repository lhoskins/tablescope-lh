"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface SaveCardToDashboardResponse {
  status: string;
  dashboard_id: number;
  name: string;
  project_id: number;
  query_id: number;
  widget_id: string;
}