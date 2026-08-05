"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { TimeSeriesInterval } from "./time-series-interval";
import { TimeSeriesRange } from "./time-series-range";
import { TimeSeriesResponse } from "./time-series-response";



export function getInsightTimeSeries(
  insightId: string,
  params: {
    project_id: number;
    interval: TimeSeriesInterval;
    range: TimeSeriesRange;
  },
): Promise<TimeSeriesResponse> {
  const query = new URLSearchParams();
  query.set("project_id", String(params.project_id));
  query.set("interval", params.interval);
  query.set("range", params.range);
  return apiClient.get(`/api/ai/insights/${insightId}/time-series?${query.toString()}`);
}