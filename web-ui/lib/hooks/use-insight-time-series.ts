"use client";

import { useQuery } from "@tanstack/react-query";
import {
  getInsightTimeSeries,
  type TimeSeriesInterval,
  type TimeSeriesRange,
  type TimeSeriesResponse,
} from "@/lib/api/home-intelligence";

function timeSeriesQueryKey(
  insightId: string,
  projectId: number,
  interval: TimeSeriesInterval,
  range: TimeSeriesRange,
) {
  return ["insight-time-series", insightId, projectId, interval, range];
}

export function useInsightTimeSeries(
  insightId: string | undefined,
  projectId: number | undefined,
  interval: TimeSeriesInterval,
  range: TimeSeriesRange,
  enabled = true,
) {
  return useQuery<TimeSeriesResponse>({
    queryKey: timeSeriesQueryKey(
      insightId ?? "",
      projectId ?? 0,
      interval,
      range,
    ),
    queryFn: async () => {
      if (!insightId || !projectId) {
        throw new Error("insightId and projectId required");
      }
      return getInsightTimeSeries(insightId, {
        project_id: projectId,
        interval,
        range,
      });
    },
    enabled: enabled && !!insightId && !!projectId,
    staleTime: 2 * 60 * 1000,
  });
}
