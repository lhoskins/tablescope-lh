"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { DashboardWidgetSuggestion } from "./dashboard-widget-suggestion";



export interface DashboardSuggestion {
  title: string;
  summary?: string;
  keyFindings?: string[];
  recommendedActions?: string[];
  widgets: DashboardWidgetSuggestion[];
}