"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { TimeSeriesMetric } from "./time-series-metric";
import { TimeSeriesPoint } from "./time-series-point";
import { TimeSeriesCalculation } from "./time-series-calculation";



export interface TimeSeriesResponse {
  insight_id: string;
  metric: TimeSeriesMetric;
  interval: string;
  range: string;
  timezone: string;
  comparison_label: string;
  points: TimeSeriesPoint[];
  calculation: TimeSeriesCalculation;
  warnings: string[];
  eligible: boolean;
  source_grain: string | null;
  supported_intervals: string[];
}