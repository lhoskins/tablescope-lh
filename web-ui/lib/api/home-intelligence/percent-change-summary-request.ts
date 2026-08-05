"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { TimeSeriesInterval } from "./time-series-interval";
import { TimeSeriesRange } from "./time-series-range";
import { PercentChangeSummarySort } from "./percent-change-summary-sort";



export interface PercentChangeSummaryRequest {
  project_ids: number[];
  interval: TimeSeriesInterval;
  range: TimeSeriesRange;
  search?: string;
  sort?: PercentChangeSummarySort;
  cursor?: string | null;
  page_size?: number;
}