"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { DashboardSuggestion } from "./dashboard-suggestion";



export interface DashboardSuggestionsProject {
  projectId: string;
  projectName: string;
  projectColor: string;
  dashboard: DashboardSuggestion | null;
  // M4: shared presentation descriptor + unified envelope (additive).
  presentation?: PresentationDescriptor;
  envelope?: ResponseEnvelope;
}