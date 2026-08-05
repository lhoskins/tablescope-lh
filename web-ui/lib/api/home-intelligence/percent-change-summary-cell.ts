"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface PercentChangeSummaryCell {
  current_value: number | null;
  previous_value: number | null;
  percent_change_ratio: number | null;
  status: "positive" | "negative" | "zero" | "unavailable";
  comparison_status: string;
  partial: boolean;
  warnings: string[];
}