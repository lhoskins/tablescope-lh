"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface TimeSeriesCalculation {
  formula: string;
  interval: string;
  range: string;
  range_start: string | null;
  range_end: string | null;
  as_of: string | null;
  previous_periods_included: number;
  notes: string[];
}