"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface TimeSeriesMetric {
  name: string;
  aggregation: string | null;
  is_rate_or_ratio: boolean;
  value_format: string | null;
}