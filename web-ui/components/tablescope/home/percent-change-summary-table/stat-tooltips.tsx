"use client";


import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { formatPercentChange } from "@/lib/insights/time-series";
import { insightAnchorId } from "@/lib/insights/return-target";
import type {
  PercentChangeSummaryCell,
  PercentChangeSummaryPeriod,
  PercentChangeSummaryRow,
  PercentChangeSummarySort,
  PercentChangeSummaryStatistics,
} from "@/lib/api/home-intelligence";
import {
  IconArrowUp,
  IconArrowDown,
  IconInfoCircle,
} from "@tabler/icons-react";


export const STAT_TOOLTIPS: Record<keyof PercentChangeSummaryStatistics, string> = {
  latest: "Last valid period-over-period change in chronological order",
  min: "Smallest valid period-over-period change",
  max: "Largest valid period-over-period change",
  median: "Median of valid period-over-period changes",
  average: "Arithmetic mean of valid period-over-period changes",
  standard_deviation: "Population standard deviation of valid period-over-period changes",
  cumulative_change: "First-to-last change; not a sum of period changes",
  valid_count: "Number of valid period-over-period comparisons",
};