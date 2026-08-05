"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface TimeSeriesPoint {
  label: string;
  period_start: string;
  period_end: string;
  current_value: number | null;
  previous_value: number | null;
  percent_change_ratio: number | null;
  percent_change_label: string | null;
  comparison_status: string;
  partial: boolean;
  warnings: string[];
}