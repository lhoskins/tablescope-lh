"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


// ── Cross-project percent-change summary ─────────────────────────────────────

export interface PercentChangeSummarySort {
  field: string;
  direction: "asc" | "desc";
}