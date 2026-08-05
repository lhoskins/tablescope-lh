"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


// ── Home AI suggestions — the three hero pills ───────────────────────────────

export interface QuerySuggestion {
  title: string;
  description: string;
  sql: string;
  chartType?: string;
  labelColumn?: string;
  valueColumn?: string;
}