"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface PercentChangeSummaryPageInfo {
  page_size: number;
  total_in_scope: number;
  total_eligible: number;
  total_excluded: number;
  next_cursor: string | null;
}