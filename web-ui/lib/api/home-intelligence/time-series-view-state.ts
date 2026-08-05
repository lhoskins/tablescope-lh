"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { TimeSeriesViewMode } from "./time-series-view-mode";
import { TimeSeriesInterval } from "./time-series-interval";
import { TimeSeriesRange } from "./time-series-range";



export interface TimeSeriesViewState {
  mode: TimeSeriesViewMode;
  interval: TimeSeriesInterval;
  range: TimeSeriesRange;
}