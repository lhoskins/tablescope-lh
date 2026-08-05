"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface PercentChangeSummaryStatistics {
  latest: number | null;
  min: number | null;
  max: number | null;
  median: number | null;
  average: number | null;
  standard_deviation: number | null;
  cumulative_change: number | null;
  valid_count: number;
}