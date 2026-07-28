"use client";

import { useQuery } from "@tanstack/react-query";
import {
  getPercentChangeSummary,
  type PercentChangeSummaryRequest,
  type PercentChangeSummaryResponse,
  type PercentChangeSummarySort,
  type TimeSeriesInterval,
  type TimeSeriesRange,
} from "@/lib/api/home-intelligence";

function summaryQueryKey(
  projectIds: number[],
  interval: TimeSeriesInterval,
  range: TimeSeriesRange,
  search: string,
  sort: PercentChangeSummarySort,
  cursor: string | null,
  pageSize: number,
  snapshotFingerprint: string | null,
) {
  return [
    "percent-change-summary",
    [...projectIds].sort(),
    interval,
    range,
    search,
    sort,
    cursor,
    pageSize,
    snapshotFingerprint,
  ];
}

export interface UsePercentChangeSummaryOptions {
  projectIds: number[];
  interval: TimeSeriesInterval;
  range: TimeSeriesRange;
  search?: string;
  sort?: PercentChangeSummarySort;
  cursor?: string | null;
  pageSize?: number;
  snapshotFingerprint?: string | null;
  enabled?: boolean;
}

export function usePercentChangeSummary({
  projectIds,
  interval,
  range,
  search = "",
  sort = { field: "latest_absolute_change", direction: "desc" },
  cursor = null,
  pageSize = 25,
  snapshotFingerprint = null,
  enabled = true,
}: UsePercentChangeSummaryOptions) {
  return useQuery<PercentChangeSummaryResponse>({
    queryKey: summaryQueryKey(
      projectIds,
      interval,
      range,
      search,
      sort,
      cursor,
      pageSize,
      snapshotFingerprint,
    ),
    queryFn: ({ signal }) =>
      getPercentChangeSummary(
        {
          project_ids: [...projectIds].sort(),
          interval,
          range,
          search,
          sort,
          cursor,
          page_size: pageSize,
        },
        signal,
      ),
    enabled: enabled && projectIds.length > 0,
    staleTime: 2 * 60 * 1000,
    placeholderData: (previousData) => previousData,
  });
}
