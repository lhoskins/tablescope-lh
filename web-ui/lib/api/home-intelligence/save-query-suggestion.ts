"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export function saveQuerySuggestion(body: {
  project_id: number;
  name: string;
  description?: string;
  sql_text: string;
}): Promise<{ name: string; status: string; query_id: number; sql_text: string }> {
  return apiClient.post("/api/ai/actions/save-query", body);
}
